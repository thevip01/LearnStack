"use client";

import { PanelBody, PanelHint, PanelLoading, PanelToolbar, SectionTitle } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { formatDuration } from "@/lib/format";
import { useLastRun } from "@/lib/practice";
import { workspaceKey } from "@/lib/store";
import type { ExecutionStatus } from "@/lib/types";

const STATUS_META: Record<ExecutionStatus, { tone: "ok" | "warn" | "danger" | "info" | "neutral"; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "info", label: "Running" },
  succeeded: { tone: "ok", label: "Exited 0" },
  failed: { tone: "danger", label: "Failed" },
  timeout: { tone: "warn", label: "Timed out" },
  oom: { tone: "warn", label: "Out of memory" },
  cancelled: { tone: "neutral", label: "Cancelled" },
  internal_error: { tone: "danger", label: "Internal error" },
};

/** stdout / stderr as captured, never truncated by us beyond what the runner marked. */
function Stream({ title, text, tone }: { title: string; text: string; tone: "ink" | "danger" }) {
  return (
    <section className="min-h-0">
      <SectionTitle>{title}</SectionTitle>
      <pre
        className={
          tone === "danger"
            ? "mt-1 max-h-72 overflow-auto rounded border border-danger/20 bg-danger/5 p-2 font-mono text-2xs leading-4 text-danger/90"
            : "mt-1 max-h-72 overflow-auto rounded border border-line bg-canvas/60 p-2 font-mono text-2xs leading-4 text-ink"
        }
      >
        {text}
      </pre>
    </section>
  );
}

/**
 * Raw program output for the last run in this workspace.
 *
 * Reads the same store slot the editor writes to on Run or Submit, so it needs no
 * task of its own: whatever executed last shows here. Test outcomes live in the
 * test-results panel; this one is only stdout, stderr and the process's exit story.
 */
export function ConsolePanel({ runtime, mode }: PanelProps) {
  const workspace = workspaceKey(runtime.id, mode);
  const { result, pending } = useLastRun(workspace);

  if (pending && !result) return <PanelLoading label="Running" rows={4} />;
  if (!result) {
    return <PanelHint title="No output yet" description="Run a coding task and its stdout and stderr will show here." />;
  }

  const meta = STATUS_META[result.status];
  const exitCode = result.usage.exit_code;
  const hasStdout = result.stdout.length > 0;
  const hasStderr = result.stderr.length > 0;

  return (
    <>
      <PanelToolbar>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        {exitCode != null ? (
          <span className="font-mono text-2xs text-faint">exit {exitCode}</span>
        ) : null}
        <span className="font-mono text-2xs text-faint">{result.runner}</span>
        {result.usage.max_memory_mb != null ? (
          <span className="font-mono text-2xs text-faint">{result.usage.max_memory_mb} MB</span>
        ) : null}
        <span className="ml-auto text-2xs text-faint">{formatDuration(result.usage.duration_ms)}</span>
      </PanelToolbar>

      <PanelBody className="space-y-3 p-pad">
        {result.error ? (
          <div className="rounded border border-danger/30 bg-danger/5 p-2 text-2xs text-danger">{result.error}</div>
        ) : null}

        {hasStdout ? <Stream title="stdout" text={result.stdout} tone="ink" /> : null}
        {hasStderr ? <Stream title="stderr" text={result.stderr} tone="danger" /> : null}

        {!hasStdout && !hasStderr && !result.error ? (
          <p className="text-2xs text-faint">No output.</p>
        ) : null}

        {result.truncated ? (
          <p className="text-2xs text-warn">Output was truncated by the sandbox.</p>
        ) : null}
      </PanelBody>
    </>
  );
}
