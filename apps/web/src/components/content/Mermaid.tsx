"use client";

import { useEffect, useId, useRef, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";

/**
 * Mermaid is imported lazily on the client only: it is ~500kB and pulls in a DOM
 * measuring pass, so a lesson without a diagram must not pay for it.
 */
export function Mermaid({ source, className }: { source: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState<string | null>(null);
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "strict",
          fontFamily: "var(--os-font-sans)",
          themeVariables: { darkMode: true, background: "transparent" },
        });
        const { svg } = await mermaid.render(`mermaid-${id}`, source);
        if (cancelled) return;
        if (containerRef.current) containerRef.current.innerHTML = svg;
        setState("ready");
      } catch (error) {
        if (cancelled) return;
        setMessage(error instanceof Error ? error.message : "diagram failed to render");
        setState("error");
      }
    }

    setState("loading");
    void render();
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (state === "error") {
    return (
      <EmptyState
        tone="error"
        title="Diagram could not be rendered"
        description={message ?? "The mermaid source in this content block is not valid."}
      >
        <pre className="max-h-40 overflow-auto rounded border border-line bg-canvas p-2 font-mono text-2xs text-muted">
          {source}
        </pre>
      </EmptyState>
    );
  }

  return (
    <div className={className}>
      {state === "loading" ? (
        <div className="flex items-center gap-2 p-3 text-xs text-muted">
          <Spinner className="size-3" /> Rendering diagram
        </div>
      ) : null}
      <div ref={containerRef} className="[&_svg]:h-auto [&_svg]:max-w-full" />
    </div>
  );
}
