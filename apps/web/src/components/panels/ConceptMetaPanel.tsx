"use client";

import { AlertTriangle, Check, Lock, X } from "lucide-react";
import Link from "next/link";
import { Markdown } from "@/components/content/Markdown";
import { PanelBody, PanelError, PanelHint, PanelLoading, SectionTitle } from "@/components/panels/shared/PanelShell";
import { useNavItem } from "@/components/runtime/nav";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { formatPercent } from "@/lib/format";
import { useConcept } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * The "what am I looking at" rail: the skills a concept builds, whether its
 * prerequisites are met, and the failure modes worth knowing before the reading.
 * Everything is a projection of the ConceptOut: no local knowledge of the subject.
 */
export function ConceptMetaPanel({ runtime, nodeId }: PanelProps) {
  const navItem = useNavItem(runtime, nodeId);
  const isConcept = navItem?.kind === "concept";
  const { data: concept, isLoading, error } = useConcept(runtime.id, isConcept ? nodeId : null);

  const skillTitle = new Map(runtime.skills.map((skill) => [skill.id, skill.title]));

  if (!isConcept) return <PanelHint title="No concept selected" description="Concept details appear here." />;
  if (isLoading) return <PanelLoading label="Loading concept details" rows={5} />;
  if (error) return <PanelError error={error} />;
  if (!concept) return <PanelHint title="Unavailable" />;

  return (
    <PanelBody className="space-y-4 p-pad">
      <section>
        <SectionTitle>Builds skills</SectionTitle>
        {concept.skills.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {concept.skills.map((id) => (
              <Link key={id} href={routes.progress(runtime.id)}>
                <Badge tone="accent" className="hover:border-accent">
                  {skillTitle.get(id) ?? id}
                </Badge>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-2xs text-faint">No skills tagged.</p>
        )}
      </section>

      {concept.prerequisite_status.length > 0 ? (
        <section>
          <SectionTitle>Prerequisites</SectionTitle>
          <ul className="space-y-1">
            {concept.prerequisite_status.map((prereq) => (
              <li
                key={prereq.concept_id}
                className="flex items-center gap-2 rounded border border-line bg-surface px-2 py-1 text-xs"
              >
                <span className={cn("shrink-0", prereq.ready ? "text-ok" : "text-warn")}>
                  {prereq.ready ? <Check className="size-3.5" aria-hidden /> : <Lock className="size-3.5" aria-hidden />}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink">{prereq.title}</span>
                <span className="shrink-0 font-mono text-2xs text-faint">{formatPercent(prereq.mastery)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {concept.components.length > 0 ? (
        <section>
          <SectionTitle>Anatomy</SectionTitle>
          <dl className="space-y-1.5">
            {concept.components.map((component) => (
              <div key={component.name} className="rounded border border-line bg-surface px-2 py-1.5">
                <dt className="flex items-center gap-1.5 text-xs font-medium text-ink">
                  <span className="font-mono text-accent">{component.name}</span>
                  {component.required ? <Badge tone="neutral">required</Badge> : null}
                </dt>
                <dd className="mt-0.5 text-2xs text-muted">{component.role}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {concept.common_errors.length > 0 ? (
        <section>
          <SectionTitle>Common errors</SectionTitle>
          <ul className="space-y-1.5">
            {concept.common_errors.map((entry, index) => (
              <li key={index} className="rounded border border-warn/30 bg-warn/5 px-2 py-1.5">
                <div className="flex items-start gap-1.5 text-xs font-medium text-ink">
                  <AlertTriangle className="mt-0.5 size-3 shrink-0 text-warn" aria-hidden />
                  <span>{entry.error}</span>
                </div>
                <p className="mt-1 text-2xs text-muted">
                  <span className="text-faint">Cause: </span>
                  {entry.cause}
                </p>
                <p className="mt-0.5 text-2xs text-muted">
                  <span className="text-faint">Fix: </span>
                  {entry.fix}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {concept.anti_patterns.length > 0 ? (
        <section>
          <SectionTitle>Anti-patterns</SectionTitle>
          <ul className="space-y-1">
            {concept.anti_patterns.map((item, index) => (
              <li key={index} className="flex items-start gap-1.5 text-2xs text-muted">
                <X className="mt-0.5 size-3 shrink-0 text-danger" aria-hidden />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {concept.best_practices.length > 0 ? (
        <section>
          <SectionTitle>Best practices</SectionTitle>
          <ul className="space-y-1">
            {concept.best_practices.map((item, index) => (
              <li key={index} className="flex items-start gap-1.5 text-2xs text-muted">
                <Check className="mt-0.5 size-3 shrink-0 text-ok" aria-hidden />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {concept.definition ? (
        <section>
          <SectionTitle>Definition</SectionTitle>
          <Markdown className="text-xs">{concept.definition}</Markdown>
        </section>
      ) : null}
    </PanelBody>
  );
}
