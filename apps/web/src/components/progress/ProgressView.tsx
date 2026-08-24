"use client";

import { PageHeader, PageShell } from "@/components/shell/Page";
import { SkillTable } from "@/components/progress/SkillTable";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonText } from "@/components/ui/Skeleton";
import { describeError } from "@/lib/api";
import { DASH, DIMENSION_LABELS, formatDimension, formatMinutes, formatScore } from "@/lib/format";
import { useProgress } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { MASTERY_DIMENSIONS, type DimensionMap, type SubjectProgressOut } from "@/lib/types";

/**
 * The mastery dashboard.
 *
 * The one rule this view exists to honour: an unmeasured dimension renders as a
 * dash, never as 0%. A learner who has read every page and run no labs is not
 * failing the lab axis: there is simply no evidence on it yet.
 */
export function ProgressView({ subjectId }: { subjectId: string }) {
  const { data, isLoading, isError, error } = useProgress(subjectId);

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Progress" back={{ href: routes.subject(subjectId), label: "Back to subject" }} />
        <SkeletonText rows={8} />
      </PageShell>
    );
  }

  if (isError || !data) {
    const described = describeError(error);
    return (
      <PageShell>
        <PageHeader title="Progress" back={{ href: routes.subject(subjectId), label: "Back to subject" }} />
        <EmptyState
          tone={described.code === "unauthorized" ? "pending" : "error"}
          title={
            described.code === "unauthorized"
              ? "Sign in to see your progress"
              : `Could not load progress (${described.title})`
          }
          description={described.message}
        />
      </PageShell>
    );
  }

  const { summary } = data;

  return (
    <PageShell>
      <PageHeader
        title="Progress"
        subtitle={`${formatScore(summary.overall)} overall · ${formatScore(summary.coverage)} of the skill map measured`}
        back={{ href: routes.subject(subjectId), label: "Back to subject" }}
      />

      <SummaryTiles summary={summary} />
      <DimensionBars dimensions={data.dimensions} />
      <SkillTable subjectId={subjectId} skills={data.skills} />
    </PageShell>
  );
}

function SummaryTiles({ summary }: { summary: SubjectProgressOut["summary"] }) {
  const tiles: Array<{ label: string; value: string; hint?: string }> = [
    { label: "Overall", value: formatScore(summary.overall) },
    { label: "Skills mastered", value: `${summary.skills_mastered}/${summary.skills_total}` },
    { label: "At risk", value: String(summary.skills_at_risk), hint: "Mastery decaying without recent practice" },
    { label: "Concepts seen", value: String(summary.concepts_seen) },
    { label: "Practice passed", value: String(summary.practice_passed) },
    { label: "Projects done", value: String(summary.projects_completed) },
    { label: "Time practised", value: formatMinutes(summary.minutes_practised) },
    { label: "Streak", value: summary.streak_days > 0 ? `${summary.streak_days} days` : DASH },
  ];

  return (
    <ul className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
      {tiles.map((tile) => (
        <Card as="li" key={tile.label} className="px-pad py-pad-sm" >
          <div className="text-2xs text-faint" title={tile.hint}>
            {tile.label}
          </div>
          <div className="mt-0.5 text-sm font-semibold text-ink">{tile.value}</div>
        </Card>
      ))}
    </ul>
  );
}

function DimensionBars({ dimensions }: { dimensions: DimensionMap }) {
  return (
    <Card className="mb-6">
      <CardHeader
        title="Mastery by dimension"
        subtitle="Knowing a thing, doing it, and running it in production are measured separately."
      />
      <CardBody className="space-y-2.5">
        {MASTERY_DIMENSIONS.map((dimension) => {
          const score = dimensions[dimension];
          const measured = Boolean(score?.measured);
          return (
            <div key={dimension}>
              <div className="mb-1 flex items-center justify-between text-2xs">
                <span className="text-muted">{DIMENSION_LABELS[dimension]}</span>
                <span className={measured ? "font-medium text-ink" : "text-faint"}>
                  {measured ? formatDimension(score) : `${DASH} no evidence yet`}
                </span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-line">
                {measured && score ? (
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(score.score * 100)}%` }} />
                ) : null}
              </div>
            </div>
          );
        })}
      </CardBody>
    </Card>
  );
}

