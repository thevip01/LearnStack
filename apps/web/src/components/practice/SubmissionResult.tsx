"use client";

import { ArrowRight, KeyRound } from "lucide-react";
import Link from "next/link";
import { CodeSnippet } from "@/components/content/CodeSnippet";
import { Markdown } from "@/components/content/Markdown";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DIMENSION_LABELS, MASTERY_STATE_LABELS, formatDuration, formatScore, masteryStateTone } from "@/lib/format";
import { targetRoute } from "@/lib/routes";
import type { LearningMode, SubmissionResultOut } from "@/lib/types";
import { SectionTitle } from "@/components/panels/shared/PanelShell";

/**
 * The graded outcome, shared by every practice kind.
 *
 * `feedback_md`, the mastery deltas and `next.reason` are all rendered verbatim.
 * The frontend is not allowed to compose grading prose or explain a score, so
 * this component only arranges what the API said.
 */
export function SubmissionResult({
  result,
  subjectId,
  mode,
  onRetry,
}: {
  result: SubmissionResultOut;
  subjectId: string;
  mode: LearningMode;
  onRetry?: () => void;
}) {
  return (
    <div
      className={`rounded-panel border p-pad ${result.passed ? "border-ok/40 bg-ok/5" : "border-danger/40 bg-danger/5"}`}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={result.passed ? "ok" : "danger"} glyph={result.passed ? "✔" : "✘"}>
          {result.passed ? "Passed" : "Not yet"}
        </Badge>
        <span className="font-mono text-sm text-ink">{formatScore(result.score, 1)}</span>
        <span className="text-2xs text-faint">
          {DIMENSION_LABELS[result.dimension]} · {formatDuration(result.duration_ms)}
          {result.hints_used > 0 ? ` · ${result.hints_used} hint${result.hints_used === 1 ? "" : "s"} used` : ""}
        </span>
        {onRetry ? (
          <Button size="xs" variant="outline" className="ml-auto" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </div>

      <Markdown className="mt-2">{result.feedback_md}</Markdown>

      {result.mastery_deltas.length > 0 ? (
        <div className="mt-3">
          <SectionTitle>Mastery updated</SectionTitle>
          <ul className="space-y-1">
            {result.mastery_deltas.map((delta) => {
              const tone = masteryStateTone(delta.state);
              const direction = delta.after >= delta.before ? "↑" : "↓";
              return (
                <li
                  key={`${delta.skill_id}-${delta.dimension}`}
                  className="flex flex-wrap items-center gap-2 rounded border border-line bg-surface px-2 py-1 text-2xs"
                >
                  <span className="min-w-0 flex-1 truncate text-ink">{delta.title}</span>
                  <span className="text-faint">{DIMENSION_LABELS[delta.dimension]}</span>
                  <span className="font-mono text-muted">
                    {formatScore(delta.before)} <span aria-hidden>{direction}</span> {formatScore(delta.after)}
                  </span>
                  <span className={`rounded border px-1 ${tone.className}`}>
                    <span aria-hidden>{tone.glyph} </span>
                    {MASTERY_STATE_LABELS[delta.state]}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {result.unlocked_skills.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-2xs text-faint">Unlocked:</span>
          {result.unlocked_skills.map((skill) => (
            <Badge key={skill} tone="accent" glyph="+">
              {skill}
            </Badge>
          ))}
        </div>
      ) : null}

      {result.reveal ? <Reveal reveal={result.reveal} /> : null}

      {result.next ? (
        <Link
          href={targetRoute(subjectId, result.next.kind, result.next.id, mode)}
          className="mt-3 flex items-start gap-2 rounded border border-accent/40 bg-accent/5 px-2 py-1.5 text-xs hover:border-accent"
        >
          <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
          <span className="min-w-0">
            <span className="block truncate font-medium text-ink">{result.next.title}</span>
            {/* Verbatim from the recommender. */}
            <span className="block text-2xs text-muted">{result.next.reason}</span>
          </span>
        </Link>
      ) : null}
    </div>
  );
}

/** Only present once the learner passed or exhausted a solution-revealing hint. */
function Reveal({ reveal }: { reveal: NonNullable<SubmissionResultOut["reveal"]> }) {
  return (
    <div className="mt-3 rounded border border-line bg-surface p-pad">
      <div className="mb-1.5 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-muted">
        <KeyRound className="size-3" aria-hidden />
        Revealed
      </div>
      {reveal.root_cause_md ? <Markdown className="text-2xs">{reveal.root_cause_md}</Markdown> : null}
      {reveal.correct_remediations && reveal.correct_remediations.length > 0 ? (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-2xs text-muted">
          {reveal.correct_remediations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {reveal.solution_files?.map((file) => (
        <div key={file.path} className="mt-2">
          <CodeSnippet code={file.content} language={file.path.split(".").pop() ?? null} caption={file.path} maxHeight="18rem" />
        </div>
      ))}
    </div>
  );
}
