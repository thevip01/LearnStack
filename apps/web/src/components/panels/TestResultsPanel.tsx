"use client";

import { Check, X } from "lucide-react";
import { PanelBody, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { formatDuration } from "@/lib/format";
import { useLastRun } from "@/lib/practice";
import { workspaceKey } from "@/lib/store";
import type { ExecutionStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_META: Record<ExecutionStatus, { tone: "ok" | "warn" | "danger" | "info" | "neutral"; label: string; glyph: string }> = {
  queued: { tone: "neutral", label: "Queued", glyph: "•" },
  running: { tone: "info", label: "Running", glyph: "…" },
  succeeded: { tone: "ok", label: "Ran", glyph: "✔" },
  failed: { tone: "danger", label: "Failed", glyph: "✘" },
  timeout: { tone: "warn", label: "Timed out", glyph: "⏱" },
  oom: { tone: "warn", label: "Out of memory", glyph: "▲" },
  cancelled: { tone: "neutral", label: "Cancelled", glyph: "◼" },
  internal_error: { tone: "danger", label: "Internal error", glyph: "!" },
};

/**
 * Per-test outcome of the last run in this workspace.
 *
 * It reads whatever execution the store last recorded (a Run from the editor or
 * the grading of a Submit both land here), so it carries no task state of its own.
 * Only visible tests ever reach the client; hidden test bodies are graded server
 * side and never serialized, so a green board here is a real signal, not the whole
 * suite.
 */
export function TestResultsPanel({ runtime, mode }: PanelProps) {
  const workspace = workspaceKey(runtime.id, mode);
  const { result, pending } = useLastRun(workspace);

  if (pending && !result) return <PanelLoading label="Running tests" rows={4} />;
  if (!result) {
    return <PanelHint title="No run yet" description="Run or submit a coding task to see its tests here." />;
  }

  const meta = STATUS_META[result.status];
  const passedCount = result.tests.filter((test) => test.passed).length;
  const total = result.tests.length;
  const allPassed = total > 0 && passedCount === total;

  return (
    <>
      <PanelToolbar>
        <Badge tone={meta.tone} glyph={meta.glyph}>
          {meta.label}
        </Badge>
        {total > 0 ? (
          <span
            className={cn("font-mono text-xs", allPassed ? "text-ok" : "text-ink")}
          >
            {passedCount}/{total} passed
          </span>
        ) : null}
        <span className="ml-auto text-2xs text-faint">{formatDuration(result.usage.duration_ms)}</span>
      </PanelToolbar>

      <PanelBody className="space-y-2 p-pad">
        {result.error ? (
          <div className="rounded border border-danger/30 bg-danger/5 p-2 text-2xs text-danger">{result.error}</div>
        ) : null}

        {total === 0 ? (
          <p className="text-2xs text-faint">
            This run produced no test results. Check the console for program output.
          </p>
        ) : (
          <ul className="space-y-1">
            {result.tests.map((test) => (
              <li
                key={test.test_id}
                className={cn(
                  "rounded border px-2 py-1.5 text-xs",
                  test.passed ? "border-ok/30 bg-ok/5" : "border-danger/30 bg-danger/5",
                )}
              >
                <div className="flex items-center gap-2">
                  {test.passed ? (
                    <Check className="size-3.5 shrink-0 text-ok" aria-hidden />
                  ) : (
                    <X className="size-3.5 shrink-0 text-danger" aria-hidden />
                  )}
                  <span className="min-w-0 flex-1 truncate text-ink">{test.name}</span>
                  {test.weight !== 1 ? (
                    <span className="shrink-0 font-mono text-2xs text-faint">×{test.weight}</span>
                  ) : null}
                  {test.duration_ms != null ? (
                    <span className="shrink-0 text-2xs text-faint">{formatDuration(test.duration_ms)}</span>
                  ) : null}
                </div>

                {!test.passed && (test.message || test.traceback) ? (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-2xs text-muted hover:text-ink">
                      {test.message ?? "Details"}
                    </summary>
                    {test.traceback ? (
                      <pre className="mt-1 max-h-48 overflow-auto rounded bg-canvas/60 p-2 font-mono text-2xs leading-4 text-muted">
                        {test.traceback}
                      </pre>
                    ) : null}
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </PanelBody>
    </>
  );
}
