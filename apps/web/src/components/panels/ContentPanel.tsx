"use client";

import { ArrowLeft, ArrowRight, Clock } from "lucide-react";
import Link from "next/link";
import { ContentBlocks } from "@/components/content/ContentBlocks";
import { Markdown } from "@/components/content/Markdown";
import { SourceChips } from "@/components/content/SourceChips";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { Badge } from "@/components/ui/Badge";
import { useNavItem } from "@/components/runtime/nav";
import { formatMinutes } from "@/lib/format";
import { useConcept } from "@/lib/queries";
import { routes } from "@/lib/routes";
import type { PanelProps } from "@/components/runtime/types";

/**
 * The reading. Renders the concept named by the current nav node from its
 * authored content blocks — there is no subject-specific rendering here, only
 * the generic block dispatch.
 */
export function ContentPanel({ runtime, mode, nodeId }: PanelProps) {
  const navItem = useNavItem(runtime, nodeId);
  const isConcept = navItem?.kind === "concept";
  const { data: concept, isLoading, error } = useConcept(runtime.id, isConcept ? nodeId : null);

  if (!nodeId || !navItem) {
    return <PanelHint title="Nothing selected" description="Pick a concept from the curriculum to start reading." />;
  }
  if (!isConcept) {
    return (
      <PanelHint
        title={`"${navItem.title}" has no reading`}
        description="This node is a track, module or exercise. Open a concept to see its lesson here."
      />
    );
  }
  if (isLoading) return <PanelLoading label="Loading lesson" rows={6} />;
  if (error) return <PanelError error={error} />;
  if (!concept) return <PanelHint title="Lesson unavailable" />;

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{concept.title}</span>
        {concept.module ? <Badge tone="neutral">{concept.module.title}</Badge> : null}
        <span className="inline-flex items-center gap-1 text-2xs text-faint">
          <Clock className="size-3" aria-hidden />
          {formatMinutes(concept.estimated_minutes)}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {concept.prev_concept_id ? (
            <Link
              href={routes.workspace(runtime.id, mode, concept.prev_concept_id)}
              className="inline-flex h-6 items-center gap-1 rounded-md border border-transparent px-2 text-2xs font-medium text-muted hover:bg-raised hover:text-ink"
            >
              <ArrowLeft className="size-3" aria-hidden />
              Prev
            </Link>
          ) : null}
          {concept.next_concept_id ? (
            <Link
              href={routes.workspace(runtime.id, mode, concept.next_concept_id)}
              className="inline-flex h-6 items-center gap-1 rounded-md border border-line-strong px-2 text-2xs font-medium text-ink hover:bg-raised"
            >
              Next
              <ArrowRight className="size-3" aria-hidden />
            </Link>
          ) : null}
        </div>
      </PanelToolbar>

      <PanelBody className="mx-auto max-w-3xl space-y-4 p-pad">
        <header className="space-y-1.5">
          <h1 className="text-lg font-semibold text-ink">{concept.title}</h1>
          <p className="text-sm leading-relaxed text-muted">{concept.summary}</p>
        </header>

        {concept.body.length > 0 ? (
          <ContentBlocks blocks={concept.body} subjectId={runtime.id} mode={mode} />
        ) : (
          <Markdown>{concept.definition}</Markdown>
        )}

        {concept.sources.length > 0 ? (
          <footer className="border-t border-line pt-3">
            <div className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-faint">Sources</div>
            <SourceChips sources={concept.sources} />
          </footer>
        ) : null}
      </PanelBody>
    </>
  );
}
