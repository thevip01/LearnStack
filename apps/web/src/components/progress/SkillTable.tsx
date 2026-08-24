"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  DASH,
  DIMENSION_LABELS,
  formatDimension,
  formatScore,
  MASTERY_STATE_LABELS,
  masteryStateTone,
  relativeTime,
} from "@/lib/format";
import { routes } from "@/lib/routes";
import { MASTERY_DIMENSIONS, type MasteryState, type SkillMasteryOut } from "@/lib/types";

/**
 * Per-skill mastery, one row each, with every dimension as its own column.
 *
 * The grid is the point: it shows *where* a skill is weak, not just that it is.
 * Unmeasured cells are dashes, so a column of dashes reads as "never assessed
 * this way" rather than "failed".
 */
export function SkillTable({ subjectId, skills }: { subjectId: string; skills: SkillMasteryOut[] }) {
  if (skills.length === 0) {
    return (
      <EmptyState
        tone="pending"
        title="No skills measured yet"
        description="Complete a concept or a practice task and the skill map starts filling in."
      />
    );
  }

  return (
    <Card>
      <CardHeader
        title="Skills"
        subtitle={`${skills.length} tracked · a dash means that dimension has no evidence yet`}
        actions={
          <Link
            href={routes.workspace(subjectId, "review")}
            className="inline-flex h-6 items-center rounded-md border border-line bg-raised px-2 text-2xs text-muted hover:border-accent/50 hover:text-ink"
          >
            Review weak skills
          </Link>
        }
      />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-2xs">
          <thead>
            <tr className="border-b border-line bg-raised/50">
              <th scope="col" className="sticky left-0 z-10 bg-raised/95 px-pad py-1.5 font-semibold text-muted">
                Skill
              </th>
              {MASTERY_DIMENSIONS.map((dimension) => (
                <th key={dimension} scope="col" className="px-2 py-1.5 text-right font-semibold text-muted">
                  {DIMENSION_LABELS[dimension]}
                </th>
              ))}
              <th scope="col" className="px-2 py-1.5 text-right font-semibold text-muted">
                Coverage
              </th>
              <th scope="col" className="px-2 py-1.5 text-right font-semibold text-muted">
                Practised
              </th>
              <th scope="col" className="px-pad py-1.5 text-right font-semibold text-muted">
                Overall
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {skills.map((skill) => {
              const tone = masteryStateTone(skill.state);
              return (
                <tr key={skill.skill_id} className="hover:bg-raised/40">
                  <th scope="row" className="sticky left-0 z-10 max-w-[16rem] bg-surface px-pad py-1.5 font-normal">
                    <div className="truncate text-xs text-ink" title={skill.title}>
                      {skill.title}
                    </div>
                    <Badge className={`mt-0.5 ${tone.className}`} glyph={tone.glyph}>
                      {MASTERY_STATE_LABELS[skill.state as MasteryState] ?? skill.state}
                    </Badge>
                  </th>
                  {MASTERY_DIMENSIONS.map((dimension) => {
                    const score = skill.dimensions[dimension];
                    const measured = Boolean(score?.measured);
                    return (
                      <td
                        key={dimension}
                        className={`px-2 py-1.5 text-right tabular-nums ${measured ? "text-ink" : "text-faint"}`}
                        title={measured ? undefined : `No ${DIMENSION_LABELS[dimension].toLowerCase()} evidence yet`}
                      >
                        {formatDimension(score)}
                      </td>
                    );
                  })}
                  <td className="px-2 py-1.5 text-right tabular-nums text-muted">{formatScore(skill.coverage)}</td>
                  <td className="px-2 py-1.5 text-right text-faint">
                    {skill.last_practiced_at ? relativeTime(skill.last_practiced_at) : DASH}
                  </td>
                  <td className="px-pad py-1.5 text-right text-xs font-semibold tabular-nums text-ink">
                    {formatScore(skill.overall)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
