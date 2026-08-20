"use client";

import { Play } from "lucide-react";
import { useState } from "react";
import { CodeSnippet } from "@/components/content/CodeSnippet";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { formatDuration } from "@/lib/format";
import { useLastRun, useRunner } from "@/lib/practice";
import type { CodeBlock, RuntimeKind } from "@/lib/types";

/** Ad-hoc snippets need a filename in the sandbox; the runtime decides which. */
const ENTRYPOINTS: Record<RuntimeKind, string | null> = {
  python: "main.py",
  node: "main.js",
  sql: "query.sql",
  bash: "main.sh",
  terraform: "main.tf",
  browser: null,
  notebook: null,
  cloud_sim: null,
  market_sim: null,
  none: null,
};

export function RunnableCodeBlockView({ block, workspace }: { block: CodeBlock; workspace: string }) {
  const { run, pending } = useRunner(workspace);
  const { result } = useLastRun(workspace);
  const toast = useToast();
  const [ownExecutionId, setOwnExecutionId] = useState<string | null>(null);
  const entrypoint = ENTRYPOINTS[block.runtime];
  const runnable = block.runnable && entrypoint !== null;
  // Two runnable snippets in one lesson share the workspace's console, so a
  // block only shows the inline summary for the run it started itself.
  const mine = Boolean(result && ownExecutionId && result.execution_id === ownExecutionId);

  async function onRun() {
    if (!entrypoint) return;
    try {
      const outcome = await run({
        files: [{ path: entrypoint, content: block.code }],
        // Limits are advisory: the API clamps ad-hoc runs to its tightest
        // defaults regardless of what we ask for.
        limits: { runtime: block.runtime },
      });
      setOwnExecutionId(outcome.execution_id);
    } catch (error) {
      toast.push({
        tone: "error",
        title: "Run failed",
        message: error instanceof Error ? error.message : "execution service unavailable",
      });
    }
  }

  return (
    <div className="space-y-2">
      <CodeSnippet
        code={block.code}
        language={block.language ?? block.runtime}
        highlightLines={block.highlight_lines}
        caption={block.caption}
        actions={
          runnable ? (
            <Button variant="primary" size="xs" onClick={onRun} loading={pending}>
              <Play className="size-3" aria-hidden />
              Run
            </Button>
          ) : null
        }
      />

      {block.expected_output ? (
        <div className="rounded-panel border border-line bg-raised/40 p-2">
          <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-faint">Expected output</div>
          <pre className="overflow-x-auto font-mono text-2xs text-muted">{block.expected_output}</pre>
        </div>
      ) : null}

      {runnable && mine && result ? (
        <div className="rounded-panel border border-line bg-canvas p-2">
          <div className="mb-1 flex items-center gap-2">
            <Badge tone={result.status === "succeeded" ? "ok" : "danger"} glyph={result.status === "succeeded" ? "✔" : "!"}>
              {result.status}
            </Badge>
            <span className="text-2xs text-faint">
              {formatDuration(result.usage.duration_ms)} · exit {result.usage.exit_code ?? "—"}
            </span>
          </div>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-2xs text-ink/90">
            {result.stdout || result.stderr || "(no output)"}
          </pre>
          <div className="mt-1 text-2xs text-faint">Full output is in the console panel.</div>
        </div>
      ) : null}
    </div>
  );
}
