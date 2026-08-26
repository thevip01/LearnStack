"use client";

import { Activity, Bell, CheckSquare, FileCog, GitBranch, Network, Rocket, ScrollText, Search, Send, Square } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Markdown } from "@/components/content/Markdown";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar, SectionTitle } from "@/components/panels/shared/PanelShell";
import { SignInToAct, useSessionGate } from "@/components/practice/SignInToAct";
import { SubmissionResult } from "@/components/practice/SubmissionResult";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { describeError } from "@/lib/api";
import { useActiveTask, useSubmitAttempt } from "@/lib/practice";
import { useWorkspaceStore } from "@/lib/store";
import type { IncidentSignalSurface } from "@/lib/types";

/** Each signal surface gets an icon so the wall of evidence is scannable by kind. */
const SURFACE_META: Record<IncidentSignalSurface, { icon: ReactNode; label: string }> = {
  metric: { icon: <Activity className="size-3" aria-hidden />, label: "Metric" },
  log: { icon: <ScrollText className="size-3" aria-hidden />, label: "Log" },
  trace: { icon: <GitBranch className="size-3" aria-hidden />, label: "Trace" },
  config: { icon: <FileCog className="size-3" aria-hidden />, label: "Config" },
  deployment: { icon: <Rocket className="size-3" aria-hidden />, label: "Deploy" },
  topology: { icon: <Network className="size-3" aria-hidden />, label: "Topology" },
  alert: { icon: <Bell className="size-3" aria-hidden />, label: "Alert" },
};

/**
 * The incident console: read the scenario, inspect signals within a budget, choose
 * remediations and (optionally) name the root cause, then submit.
 *
 * The panel holds no answer key: `is_red_herring`, hidden payloads and the correct
 * root cause are stripped server-side, so inspecting is a real choice with a real
 * cost (`max_inspections`) that the grader scores. Every signal, symptom and
 * remediation is rendered straight from the task; nothing here is subject-aware.
 */
export function IncidentConsolePanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, workspace, isLoading, error } = useActiveTask({ runtime, mode, nodeId, panel, accept: ["incident"] });
  const submit = useSubmitAttempt(task?.id ?? null, workspace);
  const result = useWorkspaceStore((state) => (task ? state.results[task.id] : undefined));
  const gate = useSessionGate();

  const [inspected, setInspected] = useState<Set<string>>(new Set());
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [rootCause, setRootCause] = useState("");

  // Fresh scratch state whenever the incident changes.
  useEffect(() => {
    setInspected(new Set());
    setChosen(new Set());
    setRootCause("");
  }, [task?.id]);

  if (isLoading) return <PanelLoading label="Loading incident" rows={8} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No incident" description="Pick an incident scenario to open the console." />;
  if (task.kind !== "incident") {
    return <PanelHint title="Opens elsewhere" description="This task type is solved in its own panel." />;
  }

  // task is now narrowed to IncidentTaskOut.
  const budget = task.max_inspections;
  const atBudget = budget !== null && inspected.size >= budget;

  const toggleInspect = (id: string) =>
    setInspected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (!atBudget) next.add(id);
      return next;
    });

  const toggleChoice = (id: string) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onSubmit = () => {
    const trimmed = rootCause.trim();
    void submit
      .mutateAsync({
        kind: "incident",
        inspected: [...inspected],
        remediations: [...chosen],
        root_cause: trimmed.length > 0 ? trimmed : undefined,
      })
      .catch(() => {});
  };

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{task.title}</span>
        <span className="ml-auto inline-flex items-center gap-1 text-2xs text-faint">
          <Search className="size-3" aria-hidden />
          {budget === null ? `${inspected.size} inspected` : `${inspected.size}/${budget} inspected`}
        </span>
      </PanelToolbar>

      <PanelBody className="space-y-4 p-pad">
        <Markdown>{task.scenario_md}</Markdown>

        {task.symptoms.length > 0 ? (
          <section className="space-y-1.5">
            <SectionTitle>Symptoms</SectionTitle>
            <ul className="space-y-1">
              {task.symptoms.map((symptom, index) => (
                <li key={index} className="flex items-start gap-2 text-sm text-muted">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warn" aria-hidden />
                  <span className="min-w-0 flex-1 [&_*]:inline">
                    <Markdown>{symptom}</Markdown>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {task.architecture_md ? (
          <details className="rounded-panel border border-line bg-surface/50">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted hover:text-ink">Architecture</summary>
            <div className="border-t border-line px-3 py-2">
              <Markdown>{task.architecture_md}</Markdown>
            </div>
          </details>
        ) : null}

        {task.signals.length > 0 ? (
          <section className="space-y-1.5">
            <SectionTitle actions={atBudget ? <span className="text-2xs text-warn">Inspection budget reached</span> : undefined}>
              Signals
            </SectionTitle>
            <ul className="space-y-1.5">
              {task.signals.map((signal) => {
                const meta = SURFACE_META[signal.surface];
                const isOpen = inspected.has(signal.id);
                const lockedOut = !isOpen && atBudget;
                return (
                  <li key={signal.id} className="rounded-panel border border-line bg-surface">
                    <button
                      type="button"
                      onClick={() => toggleInspect(signal.id)}
                      disabled={lockedOut}
                      aria-expanded={isOpen}
                      className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-raised/40 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="inline-flex items-center gap-1 text-faint">{meta.icon}</span>
                      <span className="min-w-0 flex-1 truncate text-xs text-ink">{signal.name}</span>
                      <Badge tone="neutral">{meta.label}</Badge>
                      <span className="text-2xs text-faint">{isOpen ? "Hide" : "Inspect"}</span>
                    </button>
                    {isOpen ? (
                      <div className="border-t border-line px-2.5 py-2">
                        {signal.payload ? (
                          <pre className="overflow-auto whitespace-pre-wrap font-mono text-2xs leading-relaxed text-muted">
                            {signal.payload}
                          </pre>
                        ) : (
                          <p className="text-2xs italic text-faint">
                            Inspection recorded. This signal exposes no payload in the current build.
                          </p>
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {task.remediations.length > 0 ? (
          <section className="space-y-1.5">
            <SectionTitle>Choose remediations</SectionTitle>
            <ul className="space-y-1">
              {task.remediations.map((option) => {
                const picked = chosen.has(option.id);
                return (
                  <li key={option.id}>
                    <button
                      type="button"
                      onClick={() => toggleChoice(option.id)}
                      aria-pressed={picked}
                      className="flex w-full items-start gap-2 rounded-panel border border-line bg-surface px-2.5 py-1.5 text-left transition-colors hover:border-line-strong"
                    >
                      {picked ? (
                        <CheckSquare className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                      ) : (
                        <Square className="mt-0.5 size-4 shrink-0 text-faint" aria-hidden />
                      )}
                      <span className="min-w-0 flex-1 text-sm text-ink [&_*]:inline">
                        <Markdown>{option.md}</Markdown>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        <section className="space-y-1.5">
          <SectionTitle>Root cause (optional)</SectionTitle>
          <textarea
            value={rootCause}
            onChange={(event) => setRootCause(event.target.value)}
            rows={2}
            placeholder="In one line, what actually caused this?"
            className="w-full resize-y rounded-md border border-line bg-canvas px-2.5 py-1.5 text-sm text-ink placeholder:text-faint focus:border-accent focus:outline-none"
          />
        </section>

        {submit.error ? (
          <p className="text-2xs text-danger">{describeError(submit.error).message}</p>
        ) : null}

        <div className="flex items-center gap-2">
          {gate.locked ? (
            <SignInToAct action="act on this incident" size="sm" />
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={onSubmit}
              loading={submit.isPending}
              disabled={submit.isPending || chosen.size === 0}
            >
              <Send className="size-3" aria-hidden />
              Submit diagnosis
            </Button>
          )}
          {chosen.size === 0 ? <span className="text-2xs text-faint">Pick at least one remediation.</span> : null}
        </div>

        {result ? <SubmissionResult result={result} subjectId={runtime.id} mode={mode} /> : null}
      </PanelBody>
    </>
  );
}
