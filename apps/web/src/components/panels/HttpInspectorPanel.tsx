"use client";

import { PanelBody, PanelHint, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { useWorkspaceStore, type HttpExchange } from "@/lib/store";

function statusTone(exchange: HttpExchange): "ok" | "info" | "warn" | "danger" | "neutral" {
  if (exchange.error || exchange.status === null) return "danger";
  if (exchange.status >= 500) return "danger";
  if (exchange.status >= 400) return "warn";
  if (exchange.status >= 300) return "info";
  if (exchange.status >= 200) return "ok";
  return "neutral";
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString();
}

/** A labelled header dump, rendered only when there is something to show. */
function HeaderBlock({ title, headers }: { title: string; headers: Record<string, string> }) {
  const entries = Object.entries(headers);
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="mb-0.5 text-2xs font-medium uppercase tracking-wide text-faint">{title}</div>
      <pre className="overflow-auto rounded border border-line bg-canvas px-2 py-1 font-mono text-2xs text-muted">
        {entries.map(([key, value]) => `${key}: ${value}`).join("\n")}
      </pre>
    </div>
  );
}

/** A labelled body dump, rendered only when non-empty. */
function BodyBlock({ title, text }: { title: string; text: string | null }) {
  if (!text) return null;
  return (
    <div>
      <div className="mb-0.5 text-2xs font-medium uppercase tracking-wide text-faint">{title}</div>
      <pre className="max-h-48 overflow-auto rounded border border-line bg-canvas px-2 py-1 font-mono text-2xs leading-relaxed text-ink">
        {text}
      </pre>
    </div>
  );
}

/**
 * A read-only view of the HTTP exchanges the API client has made this session.
 *
 * It owns no requests of its own: it renders the shared `httpLog` (newest first,
 * capped in the store), so the client and the inspector are two windows onto the
 * same list. Nothing here is endpoint-aware; it just formats whatever was sent and
 * received.
 */
export function HttpInspectorPanel(_: PanelProps) {
  const httpLog = useWorkspaceStore((state) => state.httpLog);

  if (httpLog.length === 0) {
    return <PanelHint title="No requests yet" description="Requests you send from the API client are captured here." />;
  }

  return (
    <>
      <PanelToolbar>
        <span className="text-xs font-medium text-ink">Exchanges</span>
        <Badge tone="neutral">{httpLog.length}</Badge>
        <span className="ml-auto text-2xs text-faint">newest first</span>
      </PanelToolbar>

      <PanelBody className="space-y-1.5 p-pad">
        {httpLog.map((exchange) => (
          <details key={exchange.id} className="rounded-panel border border-line bg-surface">
            <summary className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5">
              <span className="shrink-0 rounded border border-line bg-raised px-1 font-mono text-2xs text-muted">
                {exchange.method}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-2xs text-ink">{exchange.url}</span>
              <Badge tone={statusTone(exchange)}>{exchange.error ? "ERR" : exchange.status}</Badge>
              <span className="shrink-0 text-2xs text-faint">{exchange.durationMs}ms</span>
            </summary>
            <div className="space-y-2 border-t border-line px-2.5 py-2">
              <div className="text-2xs text-faint">{formatTime(exchange.at)}</div>
              {exchange.error ? <p className="text-2xs text-danger">{exchange.error}</p> : null}
              <HeaderBlock title="Request headers" headers={exchange.requestHeaders} />
              <BodyBlock title="Request body" text={exchange.requestBody} />
              <HeaderBlock title="Response headers" headers={exchange.responseHeaders} />
              <BodyBlock title="Response body" text={exchange.responseBody} />
            </div>
          </details>
        ))}
      </PanelBody>
    </>
  );
}
