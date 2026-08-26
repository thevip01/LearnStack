"use client";

import {
  PanelBody,
  PanelError,
  PanelHint,
  PanelLoading,
  PanelToolbar,
  SectionTitle,
} from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import {
  DASH,
  DIMENSION_LABELS,
  MASTERY_STATE_LABELS,
  formatDimension,
  formatMinutes,
  formatPercent,
  masteryStateTone,
  relativeTime,
  titleCase,
} from "@/lib/format";
import { useProgress } from "@/lib/queries";
import type { DimensionScore, MasteryDimension, MasteryState } from "@/lib/types";

/**
 * The learner's mastery for this subject: the six dimensions and the per-skill
 * rollup, straight from `/progress`. Unmeasured dimensions render a dash, never
 * 0%: a learner who has read but not practised has *no evidence* on the doing
 * axes, which is not the same as failing them.
 */
export function MasteryPanel({ runtime }: PanelProps) {
  const { data: progress, isLoading, error } = useProgress(runtime.id);

  if (isLoading) return <PanelLoading label="Loading mastery" rows={6} />;
  if (error) return <PanelError error={error} />;
  if (!progress) return <PanelHint title="No progress yet" description="Sign in and practise to build mastery." />;

  const { summary, dimensions, skills } = progress;
  const dimensionOrder = Object.keys(DIMENSION_LABELS) as MasteryDimension[];
  const rankedSkills = [...skills].sort((a, b) => b.overall - a.overall);

  return (
    <>
      <PanelToolbar>
        <span className="text-2xs font-semibold uppercase tracking-wide text-faint">Mastery</span>
        <span className="ml-auto font-mono text-xs text-ink">{formatPercent(summary.overall)}</span>
      </PanelToolbar>

      <PanelBody className="space-y-4 p-pad">
        <section className="grid grid-cols-2 gap-2">
          <Stat label="Overall" value={formatPercent(summary.overall)} />
          <Stat label="Coverage" value={formatPercent(summary.coverage)} />
          <Stat label="Skills mastered" value={`${summary.skills_mastered}/${summary.skills_total}`} />
          <Stat
            label="At risk"
            value={String(summary.skills_at_risk)}
            tone={summary.skills_at_risk > 0 ? "danger" : "neutral"}
          />
          <Stat label="Practice passed" value={String(summary.practice_passed)} />
          <Stat label="Streak" value={summary.streak_days > 0 ? `${summary.streak_days}d` : DASH} />
        </section>

        <section>
          <SectionTitle>Dimensions</SectionTitle>
          <ul className="space-y-1.5">
            {dimensionOrder.map((dimension) => (
              <DimensionRow key={dimension} label={DIMENSION_LABELS[dimension]} score={dimensions[dimension]} />
            ))}
          </ul>
        </section>

        <section>
          <SectionTitle>Skills</SectionTitle>
          {rankedSkills.length > 0 ? (
            <ul className="space-y-1">
              {rankedSkills.map((skill) => {
                const tone = masteryStateTone(skill.state);
                const label = MASTERY_STATE_LABELS[skill.state as MasteryState] ?? titleCase(skill.state);
                return (
                  <li
                    key={skill.skill_id}
                    className="flex items-center gap-2 rounded border border-line bg-surface px-2 py-1 text-xs"
                    // The relative time lives here rather than in the row. In a
                    // 290px panel it was the element that pushed the title out:
                    // three shrink-0 siblings against one truncating span left the
                    // most practised skill rendering as the single letter "S".
                    title={skill.last_practiced_at ? `${skill.title}, last practised ${relativeTime(skill.last_practiced_at)}` : skill.title}
                  >
                    <span className="min-w-0 flex-1 truncate text-ink">{skill.title}</span>
                    <span className="shrink-0 font-mono text-2xs text-muted">{formatPercent(skill.overall)}</span>
                    <span className={`shrink-0 rounded border px-1 text-2xs ${tone.className}`} title={label}>
                      <span aria-hidden>{tone.glyph} </span>
                      {label}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-2xs text-faint">This subject declares no skills.</p>
          )}
        </section>
      </PanelBody>
    </>
  );
}

function Stat({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "danger" }) {
  return (
    <div className="rounded border border-line bg-surface px-2 py-1.5">
      <div className="text-2xs text-faint">{label}</div>
      <div className={`font-mono text-sm ${tone === "danger" ? "text-danger" : "text-ink"}`}>{value}</div>
    </div>
  );
}

function DimensionRow({ label, score }: { label: string; score: DimensionScore | undefined }) {
  const measured = Boolean(score?.measured);
  const pct = measured && score ? Math.round(score.score * 100) : 0;
  return (
    <li className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-2xs text-muted">{label}</span>
      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised" aria-hidden>
        <span
          className={`block h-full rounded-full ${measured ? "bg-accent" : "bg-transparent"}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="w-10 shrink-0 text-right font-mono text-2xs text-faint">{formatDimension(score)}</span>
    </li>
  );
}
