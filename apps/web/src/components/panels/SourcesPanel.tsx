"use client";

import { BookMarked, ExternalLink } from "lucide-react";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { useNavItem } from "@/components/runtime/nav";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { relativeTime, titleCase } from "@/lib/format";
import { useConcept } from "@/lib/queries";
import type { SourceRef } from "@/lib/types";

/**
 * Provenance for the current reading. Every claim in a concept cites a
 * registered source; this panel is where a learner checks one rather than
 * trusting it. Sources are collected from the concept and its prose blocks and
 * de-duplicated by id.
 */
export function SourcesPanel({ runtime, nodeId }: PanelProps) {
  const navItem = useNavItem(runtime, nodeId);
  const isConcept = navItem?.kind === "concept";
  const { data: concept, isLoading, error } = useConcept(runtime.id, isConcept ? nodeId : null);

  if (!isConcept) return <PanelHint title="No sources" description="Open a concept to see its citations." />;
  if (isLoading) return <PanelLoading label="Loading sources" rows={4} />;
  if (error) return <PanelError error={error} />;
  if (!concept) return <PanelHint title="Unavailable" />;

  const byId = new Map<string, SourceRef>();
  for (const source of concept.sources) byId.set(source.source_id, source);
  for (const block of concept.body) {
    if (block.type === "prose") for (const source of block.sources) byId.set(source.source_id, source);
  }
  const sources = [...byId.values()];

  if (sources.length === 0) {
    return <PanelHint title="No citations" description="This concept does not cite any sources." />;
  }

  return (
    <>
      <PanelToolbar>
        <BookMarked className="size-3.5 text-faint" aria-hidden />
        <span className="text-2xs font-semibold uppercase tracking-wide text-faint">Sources</span>
        <span className="ml-auto text-2xs text-faint">{sources.length}</span>
      </PanelToolbar>
      <PanelBody className="space-y-2 p-pad">
        {sources.map((source) => {
          const label = source.title ?? source.source_id;
          const body = (
            <>
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0 text-xs font-medium text-ink">{label}</span>
                {source.url ? <ExternalLink className="mt-0.5 size-3 shrink-0 text-faint" aria-hidden /> : null}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge tone="neutral">{titleCase(source.source_type)}</Badge>
                {source.locator ? <span className="text-2xs text-muted">{source.locator}</span> : null}
              </div>
              {source.retrieved_at ? (
                <div className="mt-1 text-2xs text-faint">Retrieved {relativeTime(source.retrieved_at)}</div>
              ) : null}
            </>
          );
          return source.url ? (
            <a
              key={source.source_id}
              href={source.url}
              target="_blank"
              rel="noreferrer noopener"
              className="block rounded-panel border border-line bg-surface p-pad transition-colors hover:border-accent/50"
            >
              {body}
            </a>
          ) : (
            <div key={source.source_id} className="rounded-panel border border-line bg-surface p-pad">
              {body}
            </div>
          );
        })}
      </PanelBody>
    </>
  );
}
