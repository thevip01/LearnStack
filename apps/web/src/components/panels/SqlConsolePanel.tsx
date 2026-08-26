"use client";

import Editor from "@monaco-editor/react";
import { Database, Send } from "lucide-react";
import { useEffect } from "react";
import { CodeSnippet } from "@/components/content/CodeSnippet";
import { Markdown } from "@/components/content/Markdown";
import { PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { SignInToAct, useSessionGate } from "@/components/practice/SignInToAct";
import { SubmissionResult } from "@/components/practice/SubmissionResult";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { describeError } from "@/lib/api";
import { useActiveTask, useSubmitAttempt } from "@/lib/practice";
import { useWorkspaceStore } from "@/lib/store";

/** The query lives in the shared buffer store so it survives a mode switch. */
const QUERY_PATH = "query.sql";

/**
 * The SQL console: write a query against a provided schema and submit it for
 * grading. The panel never runs or checks the SQL itself: `schema_sql`/`seed_sql`
 * are shown for reference, and the query text is handed to the grader, which
 * executes it against the seeded database and compares results (respecting the
 * task's `ordered` flag). Query text is persisted through the workspace store, so
 * glancing at another panel and coming back does not lose it. No dialect or table
 * is baked in: everything comes from the task.
 */
export function SqlConsolePanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, workspace, isLoading, error } = useActiveTask({ runtime, mode, nodeId, panel, accept: ["sql"] });
  const seedBuffers = useWorkspaceStore((state) => state.seedBuffers);
  const setBuffer = useWorkspaceStore((state) => state.setBuffer);
  const buffers = useWorkspaceStore((state) => (task ? state.buffers[task.id] : undefined));
  const result = useWorkspaceStore((state) => (task ? state.results[task.id] : undefined));
  const submit = useSubmitAttempt(task?.id ?? null, workspace);
  const gate = useSessionGate();

  useEffect(() => {
    if (!task || task.kind !== "sql") return;
    seedBuffers(task.id, [{ path: QUERY_PATH, content: "-- Write your query here.\n" }]);
  }, [task, seedBuffers]);

  if (isLoading) return <PanelLoading label="Loading console" rows={8} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No query task" description="Pick a SQL task to open the console." />;
  if (task.kind !== "sql") {
    return <PanelHint title="Opens elsewhere" description="This task type is solved in its own panel." />;
  }

  // task is now narrowed to SQLTaskOut.
  const sql = buffers?.[QUERY_PATH] ?? "";
  const onSubmit = () => void submit.mutateAsync({ kind: "sql", sql }).catch(() => {});

  return (
    <>
      <PanelToolbar>
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink">
          <Database className="size-3.5 text-accent" aria-hidden />
          {task.title}
        </span>
        <Badge tone={task.ordered ? "warn" : "neutral"}>{task.ordered ? "order matters" : "any order"}</Badge>
        {gate.locked ? (
          <SignInToAct action="run the query" className="ml-auto" />
        ) : (
          <Button
            size="xs"
            variant="primary"
            className="ml-auto"
            onClick={onSubmit}
            loading={submit.isPending}
            disabled={submit.isPending}
          >
            <Send className="size-3" aria-hidden />
            Submit
          </Button>
        )}
      </PanelToolbar>

      <div className="max-h-32 shrink-0 overflow-auto border-b border-line px-pad py-2">
        <Markdown className="text-sm">{task.prompt_md}</Markdown>
      </div>

      {submit.error ? (
        <div className="shrink-0 border-b border-danger/30 bg-danger/5 px-pad py-1 text-2xs text-danger">
          {describeError(submit.error).message}
        </div>
      ) : null}

      <div className="min-h-32 flex-1">
        <Editor
          key={task.id}
          height="100%"
          theme="vs-dark"
          path={`${task.id}.sql`}
          language="sql"
          value={sql}
          onChange={(next) => setBuffer(task.id, QUERY_PATH, next ?? "")}
          loading={<PanelLoading label="Loading editor" rows={5} />}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: "on",
            scrollBeyondLastLine: false,
            automaticLayout: true,
            padding: { top: 10, bottom: 10 },
            scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
          }}
        />
      </div>

      <details className="shrink-0 border-t border-line" open>
        <summary className="cursor-pointer px-pad py-1.5 text-2xs font-medium uppercase tracking-wide text-muted hover:text-ink">
          Schema
        </summary>
        <div className="max-h-40 space-y-2 overflow-auto px-pad pb-2">
          <CodeSnippet code={task.schema_sql} language="sql" caption="schema" maxHeight="12rem" />
          {task.seed_sql ? <CodeSnippet code={task.seed_sql} language="sql" caption="seed data" maxHeight="10rem" /> : null}
        </div>
      </details>

      {result ? (
        <div className="max-h-64 shrink-0 overflow-auto border-t border-line p-pad">
          <SubmissionResult result={result} subjectId={runtime.id} mode={mode} />
        </div>
      ) : null}
    </>
  );
}
