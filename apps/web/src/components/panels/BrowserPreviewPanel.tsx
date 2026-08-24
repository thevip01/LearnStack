"use client";

import { Globe } from "lucide-react";
import { PanelHint, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { useLastRun } from "@/lib/practice";
import { workspaceKey } from "@/lib/store";
import { cfgString, recordEntry } from "@/lib/utils";

const HTML_RE = /\.html?$/i;

/** Pick the HTML artifact to show: an explicit entry, else the first .html, else a lone artifact. */
function pickHtml(artifacts: Record<string, string>, entry: string | null): { name: string; content: string } | null {
  const keys = Object.keys(artifacts);
  return (
    recordEntry(artifacts, entry) ??
    recordEntry(
      artifacts,
      keys.find((key) => HTML_RE.test(key)),
    ) ??
    (keys.length === 1 ? recordEntry(artifacts, keys[0]) : null)
  );
}

/**
 * Renders a web preview in a locked-down iframe. Two sources, in order: an explicit
 * `url` in the panel config (previewed as a page), or an HTML artifact produced by
 * the workspace's last run (previewed via `srcDoc`). The frame is sandboxed to
 * `allow-scripts` only (no same-origin access to this app), so learner or task
 * output cannot reach the surrounding page. The panel is subject-agnostic: it shows
 * whatever HTML the run emitted, whatever the subject.
 */
export function BrowserPreviewPanel({ runtime, mode, panel }: PanelProps) {
  const externalUrl = cfgString(panel.config, "url") ?? cfgString(panel.config, "src");
  const entry = cfgString(panel.config, "entry");
  const { result } = useLastRun(workspaceKey(runtime.id, mode));
  const html = !externalUrl && result ? pickHtml(result.artifacts, entry) : null;

  if (externalUrl) {
    return (
      <>
        <PanelToolbar>
          <Globe className="size-3 shrink-0 text-faint" aria-hidden />
          <span className="min-w-0 flex-1 truncate font-mono text-2xs text-muted">{externalUrl}</span>
        </PanelToolbar>
        <div className="min-h-0 flex-1 bg-white">
          <iframe
            title="Web preview"
            src={externalUrl}
            sandbox="allow-scripts allow-forms"
            referrerPolicy="no-referrer"
            className="size-full border-0"
          />
        </div>
      </>
    );
  }

  if (html) {
    return (
      <>
        <PanelToolbar>
          <Globe className="size-3 shrink-0 text-faint" aria-hidden />
          <span className="min-w-0 flex-1 truncate font-mono text-2xs text-muted">{html.name}</span>
          <Badge tone="neutral">from last run</Badge>
        </PanelToolbar>
        <div className="min-h-0 flex-1 bg-white">
          <iframe
            key={`${result?.execution_id}:${html.name}`}
            title="Web preview"
            srcDoc={html.content}
            sandbox="allow-scripts allow-forms"
            className="size-full border-0"
          />
        </div>
      </>
    );
  }

  return (
    <PanelHint
      title="Nothing to preview"
      description="Run a task that emits an HTML artifact, or set this panel's url config to preview a page."
    />
  );
}
