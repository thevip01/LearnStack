"use client";

import { ArrowUpRight, Dumbbell } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { difficultyLabel, titleCase } from "@/lib/format";
import { usePracticeTask } from "@/lib/practice";
import { targetRoute } from "@/lib/routes";
import type { LearningMode } from "@/lib/types";

/**
 * A practice task referenced from inside a lesson (`embed_practice`).
 *
 * It resolves to a link into `practice` mode rather than running the task in
 * place: an attempt has a lifecycle (hints, submissions, mastery deltas) that
 * belongs in the practice workspace, not spliced into scrolling prose. The card
 * still previews what the learner is walking into: kind, difficulty, hints.
 */
export function EmbeddedPractice({
  practiceId,
  subjectId,
  mode,
}: {
  practiceId: string;
  subjectId: string;
  mode: LearningMode;
}) {
  const { data, isLoading, error } = usePracticeTask(practiceId);

  if (isLoading) {
    return <div className="skeleton-bar h-14 w-full rounded-panel" aria-label="Loading practice" />;
  }

  if (error || !data) {
    return (
      <div className="rounded-panel border border-line bg-raised/40 px-pad py-2 text-2xs text-faint">
        Embedded practice <span className="font-mono">{practiceId}</span> is unavailable.
      </div>
    );
  }

  return (
    <Link
      href={targetRoute(subjectId, "practice", data.id, mode === "learn" ? "practice" : mode)}
      className="flex items-start gap-3 rounded-panel border border-accent/30 bg-accent/5 px-pad py-2.5 transition-colors hover:border-accent"
    >
      <Dumbbell className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{data.title}</span>
          <Badge tone="neutral">{titleCase(data.kind)}</Badge>
        </span>
        <span className="mt-0.5 block text-2xs text-muted">
          Practice · difficulty {difficultyLabel(data.difficulty)}
          {data.hint_count > 0 ? ` · ${data.hint_count} hint${data.hint_count === 1 ? "" : "s"}` : ""}
        </span>
      </span>
      <ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
    </Link>
  );
}
