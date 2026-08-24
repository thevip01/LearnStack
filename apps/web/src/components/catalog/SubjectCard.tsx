"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { formatMinutes, formatScore } from "@/lib/format";
import { routes } from "@/lib/routes";
import { themeCssVars } from "@/lib/theme";
import type { CatalogSubject } from "@/lib/types";

const MAX_TAGS = 3;

/**
 * One shelf card.
 *
 * The subject's own ThemeSpec is applied as CSS custom properties on the card,
 * so the accent on the progress bar and the hover border come from the subject
 * package rather than from any per-subject rule in this file.
 */
export function SubjectCard({ subject }: { subject: CatalogSubject }) {
  const { progress } = subject;
  const tags = subject.tags.slice(0, MAX_TAGS);
  const hiddenTags = subject.tags.length - tags.length;

  return (
    <Card
      as="li"
      style={themeCssVars(subject.theme)}
      className="flex flex-col gap-2 p-pad transition-colors hover:border-accent/50"
    >
      <div className="flex items-start justify-between gap-2">
        <Link
          href={routes.subject(subject.id)}
          className="truncate text-sm font-semibold text-ink hover:text-accent"
          title={subject.title}
        >
          {subject.title}
        </Link>
        <Badge tone="neutral" title={`Package version ${subject.version}`}>
          v{subject.version}
        </Badge>
      </div>

      {subject.subtitle ? <p className="text-xs text-muted">{subject.subtitle}</p> : null}
      <p className="line-clamp-2 text-2xs leading-relaxed text-faint">{subject.description}</p>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-faint">
        <span>{subject.concept_count} concepts</span>
        <span aria-hidden>·</span>
        <span>{subject.practice_count} practice</span>
        {subject.project_count > 0 ? (
          <>
            <span aria-hidden>·</span>
            <span>{subject.project_count} projects</span>
          </>
        ) : null}
        {subject.estimated_minutes > 0 ? (
          <>
            <span aria-hidden>·</span>
            <span>{formatMinutes(subject.estimated_minutes)}</span>
          </>
        ) : null}
      </div>

      {tags.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {tags.map((tag) => (
            <Badge key={tag} tone="neutral">
              {tag}
            </Badge>
          ))}
          {hiddenTags > 0 ? <Badge tone="neutral">+{hiddenTags}</Badge> : null}
        </div>
      ) : null}

      {/* Progress only renders with evidence behind it: no session, no bar. */}
      {progress ? (
        <div className="mt-auto pt-1">
          <div className="mb-1 flex items-center justify-between text-2xs">
            <span className="text-muted">
              {progress.skills_mastered}/{progress.skills_total} skills mastered
            </span>
            <span className="font-medium text-ink">{formatScore(progress.overall)}</span>
          </div>
          <div
            className="h-1 overflow-hidden rounded-full bg-line"
            role="img"
            aria-label={`${formatScore(progress.overall)} overall mastery`}
          >
            <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(progress.overall * 100)}%` }} />
          </div>
        </div>
      ) : (
        <div className="mt-auto pt-1 text-2xs text-faint">{subject.provider ?? "Not started"}</div>
      )}
    </Card>
  );
}
