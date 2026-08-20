import { ExternalLink } from "lucide-react";
import { relativeTime, titleCase } from "@/lib/format";
import type { SourceRef } from "@/lib/types";

/**
 * Compact citation row. Every claim in the platform carries these; showing them
 * inline is what lets a learner check a statement instead of trusting it.
 */
export function SourceChips({ sources, className }: { sources: SourceRef[]; className?: string }) {
  if (sources.length === 0) return null;
  return (
    <ul className={className ?? "mt-2 flex flex-wrap gap-1.5"}>
      {sources.map((source, index) => {
        const label = source.title ?? source.source_id;
        const body = (
          <>
            <span className="font-mono text-2xs text-faint">{titleCase(source.source_type)}</span>
            <span className="truncate">{label}</span>
            {source.locator ? <span className="text-faint">· {source.locator}</span> : null}
            {source.url ? <ExternalLink className="size-2.5 shrink-0" aria-hidden /> : null}
          </>
        );
        const title = source.retrieved_at ? `Retrieved ${relativeTime(source.retrieved_at)}` : undefined;
        return (
          <li key={`${source.source_id}-${index}`} className="max-w-full">
            {source.url ? (
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                title={title}
                className="inline-flex max-w-full items-center gap-1.5 rounded border border-line bg-raised px-1.5 py-0.5 text-2xs text-muted hover:border-accent/50 hover:text-ink"
              >
                {body}
              </a>
            ) : (
              <span
                title={title}
                className="inline-flex max-w-full items-center gap-1.5 rounded border border-line bg-raised px-1.5 py-0.5 text-2xs text-muted"
              >
                {body}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
