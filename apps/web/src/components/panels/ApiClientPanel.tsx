"use client";

import { Send } from "lucide-react";
import { useEffect, useState } from "react";
import { Markdown } from "@/components/content/Markdown";
import { PanelBody, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useActiveTask } from "@/lib/practice";
import { useWorkspaceStore, type HttpExchange } from "@/lib/store";
import { cfgString } from "@/lib/utils";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] as const;
type Method = (typeof METHODS)[number];

/** Parse a "Key: Value" per line header block into a header map. */
function parseHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const idx = line.indexOf(":");
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim();
    if (key) out[key] = line.slice(idx + 1).trim();
  }
  return out;
}

function statusTone(exchange: HttpExchange): "ok" | "info" | "warn" | "danger" | "neutral" {
  if (exchange.error || exchange.status === null) return "danger";
  if (exchange.status >= 500) return "danger";
  if (exchange.status >= 400) return "warn";
  if (exchange.status >= 300) return "info";
  if (exchange.status >= 200) return "ok";
  return "neutral";
}

/**
 * A minimal HTTP client for API tasks. It carries no submission (the wire schema
 * has no `api` attempt), so this is a pure exploration surface: fire a request at
 * the task's `base_url`, see the response, and drop every exchange into the shared
 * `httpLog` that the HTTP inspector reads. The request runs from the browser, so
 * cross-origin rules apply and any failure is surfaced verbatim rather than hidden.
 * The endpoint, guide and method set are all data: nothing is API-specific here.
 */
export function ApiClientPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task } = useActiveTask({ runtime, mode, nodeId, panel, accept: ["api"] });
  const pushHttpExchange = useWorkspaceStore((state) => state.pushHttpExchange);

  const configBase = cfgString(panel.config, "base_url");
  const [method, setMethod] = useState<Method>("GET");
  const [url, setUrl] = useState("");
  const [headersText, setHeadersText] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [sending, setSending] = useState(false);
  const [latest, setLatest] = useState<HttpExchange | null>(null);

  const spec = task?.kind === "api" ? task.requests_spec_md : null;

  // Seed the URL from the task's base_url (or config) once it is known, without
  // clobbering a URL the learner has started editing.
  useEffect(() => {
    const base = (task?.kind === "api" ? task.base_url : null) ?? configBase;
    if (base) setUrl((current) => (current ? current : base));
  }, [task, configBase]);

  const hasBody = method !== "GET" && method !== "HEAD";

  const send = async () => {
    const target = url.trim();
    if (!target || sending) return;
    setSending(true);
    const requestHeaders = parseHeaders(headersText);
    const requestBody = hasBody && bodyText ? bodyText : null;
    const started = performance.now();
    const base: HttpExchange = {
      id: crypto.randomUUID(),
      method,
      url: target,
      requestHeaders,
      requestBody,
      status: null,
      statusText: "",
      responseHeaders: {},
      responseBody: "",
      durationMs: 0,
      error: null,
      at: new Date().toISOString(),
    };
    try {
      const response = await fetch(target, { method, headers: requestHeaders, body: requestBody ?? undefined });
      const responseBody = await response.text();
      const responseHeaders: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        responseHeaders[key] = value;
      });
      const exchange: HttpExchange = {
        ...base,
        status: response.status,
        statusText: response.statusText,
        responseHeaders,
        responseBody,
        durationMs: Math.round(performance.now() - started),
      };
      pushHttpExchange(exchange);
      setLatest(exchange);
    } catch (error) {
      const exchange: HttpExchange = {
        ...base,
        error: error instanceof Error ? error.message : "request failed",
        durationMs: Math.round(performance.now() - started),
      };
      pushHttpExchange(exchange);
      setLatest(exchange);
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PanelToolbar className="gap-1.5">
        <select
          value={method}
          onChange={(event) => setMethod(event.target.value as Method)}
          className="h-7 shrink-0 rounded-md border border-line bg-canvas px-1.5 font-mono text-2xs text-ink focus:border-accent focus:outline-none"
          aria-label="HTTP method"
        >
          {METHODS.map((entry) => (
            <option key={entry} value={entry}>
              {entry}
            </option>
          ))}
        </select>
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void send();
          }}
          placeholder="https://api.example.com/resource"
          spellCheck={false}
          className="h-7 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2 font-mono text-2xs text-ink placeholder:text-faint focus:border-accent focus:outline-none"
        />
        <Button size="xs" variant="primary" onClick={() => void send()} loading={sending} disabled={sending}>
          <Send className="size-3" aria-hidden />
          Send
        </Button>
      </PanelToolbar>

      <PanelBody className="space-y-3 p-pad">
        {spec ? (
          <details className="rounded-panel border border-line bg-surface/50">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted hover:text-ink">Request guide</summary>
            <div className="border-t border-line px-3 py-2">
              <Markdown>{spec}</Markdown>
            </div>
          </details>
        ) : null}

        <details className="rounded-panel border border-line bg-surface/50">
          <summary className="cursor-pointer px-3 py-2 text-2xs font-medium uppercase tracking-wide text-muted hover:text-ink">
            Headers
          </summary>
          <div className="border-t border-line p-2">
            <textarea
              value={headersText}
              onChange={(event) => setHeadersText(event.target.value)}
              rows={2}
              spellCheck={false}
              placeholder={"Authorization: Bearer …\nContent-Type: application/json"}
              className="w-full resize-y rounded border border-line bg-canvas px-2 py-1 font-mono text-2xs text-ink placeholder:text-faint focus:border-accent focus:outline-none"
            />
          </div>
        </details>

        {hasBody ? (
          <div>
            <div className="mb-1 text-2xs font-medium uppercase tracking-wide text-faint">Body</div>
            <textarea
              value={bodyText}
              onChange={(event) => setBodyText(event.target.value)}
              rows={4}
              spellCheck={false}
              placeholder={'{ "key": "value" }'}
              className="w-full resize-y rounded border border-line bg-canvas px-2 py-1 font-mono text-2xs text-ink placeholder:text-faint focus:border-accent focus:outline-none"
            />
          </div>
        ) : null}

        {latest ? (
          <section className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={statusTone(latest)} glyph={latest.error ? "✘" : undefined}>
                {latest.error ? "Failed" : `${latest.status} ${latest.statusText}`.trim()}
              </Badge>
              <span className="font-mono text-2xs text-faint">
                {latest.method} · {latest.durationMs}ms
              </span>
            </div>
            {latest.error ? (
              <p className="text-2xs text-danger">
                {latest.error}. Browser requests are subject to CORS, so the endpoint may need to allow this origin.
              </p>
            ) : (
              <>
                {Object.keys(latest.responseHeaders).length > 0 ? (
                  <details className="rounded border border-line bg-surface">
                    <summary className="cursor-pointer px-2 py-1 text-2xs text-muted hover:text-ink">Response headers</summary>
                    <pre className="overflow-auto border-t border-line px-2 py-1 font-mono text-2xs text-muted">
                      {Object.entries(latest.responseHeaders)
                        .map(([key, value]) => `${key}: ${value}`)
                        .join("\n")}
                    </pre>
                  </details>
                ) : null}
                <pre className="max-h-64 overflow-auto rounded border border-line bg-canvas p-2 font-mono text-2xs leading-relaxed text-ink">
                  {latest.responseBody || "(empty body)"}
                </pre>
              </>
            )}
          </section>
        ) : (
          <p className="text-2xs text-faint">Send a request to see the response here. Every call is recorded in the HTTP inspector.</p>
        )}
      </PanelBody>
    </>
  );
}
