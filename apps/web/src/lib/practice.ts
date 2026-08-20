"use client";

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { apiFetch } from "./api";
import { qk, useConcept, usePracticeQueue } from "./queries";
import { useWorkspaceStore, workspaceKey } from "./store";
import { cfgString, cfgStringArray } from "./utils";
import {
  isExecutionAccepted,
  type AttemptOut,
  type ExecutionRequest,
  type ExecutionResult,
  type ExecutionRunResponse,
  type HintOut,
  type LearningMode,
  type Panel,
  type PracticeKind,
  type PracticeSummary,
  type PracticeTaskOut,
  type SubjectRuntimeOut,
  type SubmissionResultOut,
  type SubmitIn,
} from "./types";

export function usePracticeTask(taskId: string | null): UseQueryResult<PracticeTaskOut> {
  return useQuery({
    queryKey: qk.task(taskId ?? ""),
    queryFn: () => apiFetch<PracticeTaskOut>(`/practice/${taskId}`),
    enabled: Boolean(taskId),
  });
}

/**
 * Which task a practice panel is working on.
 *
 * Resolution is explicit so that a subject package can pin a panel to one task
 * (`config.task_id`), a learner can pick one, and a bare `practice` mode with no
 * selection still shows something useful. Selections are recorded per kind as
 * well as per workspace, so choosing a quiz does not leave the code editor
 * pointing at a task it cannot render.
 */
export function useActiveTask(args: {
  runtime: SubjectRuntimeOut;
  mode: LearningMode;
  nodeId: string | null;
  panel: Panel;
  accept?: readonly PracticeKind[];
}) {
  const { runtime, mode, nodeId, panel, accept } = args;
  const workspace = workspaceKey(runtime.id, mode);
  const selections = useWorkspaceStore((state) => state.activeTaskId);
  const setActiveTask = useWorkspaceStore((state) => state.setActiveTask);

  const navItem = useMemo(
    () => runtime.navigation.find((item) => item.id === nodeId) ?? null,
    [runtime.navigation, nodeId],
  );
  const conceptId = navItem?.kind === "concept" ? navItem.id : null;
  const concept = useConcept(runtime.id, conceptId);

  const configuredKinds = cfgStringArray(panel.config, "kinds") as PracticeKind[];
  const accepted = configuredKinds.length > 0 ? configuredKinds : accept ? [...accept] : null;

  const conceptTasks = concept.data?.practice ?? [];
  // Only fall back to the global queue when the current node offers nothing.
  const wantQueue = !conceptId || (concept.isSuccess && conceptTasks.length === 0);
  const queue = usePracticeQueue(runtime.id, null, 10, wantQueue);

  const candidates = useMemo(() => {
    const pool: PracticeSummary[] = conceptTasks.length > 0 ? conceptTasks : (queue.data?.tasks ?? []);
    return accepted ? pool.filter((task) => accepted.includes(task.kind)) : pool;
  }, [accepted, conceptTasks, queue.data?.tasks]);

  const selected = useMemo(() => {
    const pinned = cfgString(panel.config, "task_id");
    if (pinned) return pinned;
    if (accepted) {
      for (const kind of accepted) {
        const scoped = selections[`${workspace}:${kind}`];
        if (scoped) return scoped;
      }
      return candidates[0]?.id ?? null;
    }
    return selections[workspace] ?? candidates[0]?.id ?? null;
  }, [accepted, candidates, panel.config, selections, workspace]);

  const task = usePracticeTask(selected);

  const select = useCallback(
    (summary: Pick<PracticeSummary, "id" | "kind">) => {
      setActiveTask(workspace, summary.id);
      setActiveTask(`${workspace}:${summary.kind}`, summary.id);
    },
    [setActiveTask, workspace],
  );

  return {
    workspace,
    taskId: selected,
    task: task.data ?? null,
    isLoading: task.isLoading || concept.isLoading || (wantQueue && queue.isLoading),
    error: task.error ?? null,
    candidates,
    select,
    conceptId,
  };
}

// ---------------------------------------------------------------------------
// Attempt lifecycle
// ---------------------------------------------------------------------------

/** An attempt is created lazily: opening a panel is not an attempt, acting is. */
export function useEnsureAttempt(taskId: string | null) {
  const attempt = useWorkspaceStore((state) => (taskId ? state.attempts[taskId] : undefined));
  const setAttempt = useWorkspaceStore((state) => state.setAttempt);

  const mutation = useMutation({
    mutationFn: () => apiFetch<AttemptOut>(`/practice/${taskId}/attempts`, { method: "POST" }),
    onSuccess: (data) => {
      if (taskId) setAttempt(taskId, data);
    },
  });

  const ensure = useCallback(async (): Promise<AttemptOut> => {
    if (attempt) return attempt;
    return mutation.mutateAsync();
  }, [attempt, mutation]);

  return { attempt, ensure, starting: mutation.isPending, error: mutation.error };
}

export function useRequestHint(taskId: string | null) {
  const addHint = useWorkspaceStore((state) => state.addHint);
  const hints = useWorkspaceStore((state) => (taskId ? state.hints[taskId] : undefined)) ?? [];
  const { ensure } = useEnsureAttempt(taskId);

  const mutation = useMutation({
    mutationFn: async () => {
      const attempt = await ensure();
      return apiFetch<HintOut>(`/practice/${taskId}/attempts/${attempt.attempt_id}/hint`, { method: "POST" });
    },
    onSuccess: (hint) => {
      if (taskId) addHint(taskId, hint);
    },
  });

  return { hints, request: mutation.mutateAsync, pending: mutation.isPending, error: mutation.error };
}

export function useSubmitAttempt(taskId: string | null, workspace: string) {
  const client = useQueryClient();
  const setResult = useWorkspaceStore((state) => state.setResult);
  const setRun = useWorkspaceStore((state) => state.setRun);
  const { ensure } = useEnsureAttempt(taskId);

  return useMutation({
    mutationFn: async (payload: SubmitIn) => {
      const attempt = await ensure();
      return apiFetch<SubmissionResultOut>(`/practice/${taskId}/attempts/${attempt.attempt_id}/submit`, {
        method: "POST",
        body: payload,
      });
    },
    onSuccess: (result) => {
      if (!taskId) return;
      setResult(taskId, result);
      // The console and test-results panels read the workspace's last execution,
      // whether it came from a Run button or from grading a submission.
      if (result.execution) setRun(workspace, result.execution);
      for (const key of [["progress"], ["subject"], ["concept"], ["queue"], ["next"]]) {
        client.invalidateQueries({ queryKey: key });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Ad-hoc execution
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 800;
const POLL_LIMIT = 60;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 200 answers inline; 202 hands back an id that has to be polled to completion. */
async function runToCompletion(request: ExecutionRequest): Promise<ExecutionResult> {
  const response = await apiFetch<ExecutionRunResponse>("/execution/runs", { method: "POST", body: request });
  if (!isExecutionAccepted(response)) return response;

  for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
    await sleep(POLL_INTERVAL_MS);
    const polled = await apiFetch<ExecutionResult>(`/execution/runs/${response.execution_id}`);
    if (polled.status !== "queued" && polled.status !== "running") return polled;
  }
  throw new Error("execution did not finish before the client stopped polling");
}

export function useRunner(workspace: string) {
  const setRun = useWorkspaceStore((state) => state.setRun);
  const setRunPending = useWorkspaceStore((state) => state.setRunPending);

  const mutation = useMutation({
    mutationFn: (request: ExecutionRequest) => runToCompletion(request),
    onMutate: () => setRunPending(workspace, true),
    onSettled: () => setRunPending(workspace, false),
    onSuccess: (result) => setRun(workspace, result),
  });

  return { run: mutation.mutateAsync, pending: mutation.isPending, error: mutation.error };
}

export function useLastRun(workspace: string) {
  const result = useWorkspaceStore((state) => state.runs[workspace]);
  const pending = useWorkspaceStore((state) => state.runPending[workspace] ?? false);
  return { result, pending };
}
