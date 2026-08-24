"use client";

import { AlertTriangle, Check, MessageSquare, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonText } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { describeError } from "@/lib/api";
import { formatPercent, relativeTime, titleCase, truncateMiddle } from "@/lib/format";
import { useCandidates, useReviewCandidate } from "@/lib/queries";
import type { ExtractionCandidate, ExtractionTarget, LifecycleStatus, ReviewDecision, ValidationIssue } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_FILTERS: readonly (LifecycleStatus | null)[] = [null, "in_review", "draft", "approved", "deprecated"] as const;
const TARGET_FILTERS: readonly (ExtractionTarget | null)[] = [
  null,
  "concept",
  "curriculum",
  "practice",
  "project",
  "assessment",
] as const;

/**
 * The human gate in the pipeline.
 *
 * Extraction proposes; a reviewer decides. Nothing here auto-approves on high
 * confidence: the confidence number and the validation issues are shown side by
 * side precisely because a confident extraction can still be wrong.
 */
export function CandidateReview({ subjectId }: { subjectId: string | null }) {
  const [status, setStatus] = useState<LifecycleStatus | null>("in_review");
  const [target, setTarget] = useState<ExtractionTarget | null>(null);
  const { data, isLoading, isError, error } = useCandidates(subjectId, status, target);
  const candidates = data?.candidates ?? [];

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <FilterRow label="Status" options={STATUS_FILTERS} active={status} onChange={setStatus} />
        <FilterRow label="Target" options={TARGET_FILTERS} active={target} onChange={setTarget} />
      </div>

      {isLoading ? (
        <SkeletonText rows={6} />
      ) : isError ? (
        <EmptyState
          tone="error"
          title={`Could not load candidates (${describeError(error).title})`}
          description={describeError(error).message}
        />
      ) : candidates.length === 0 ? (
        <EmptyState
          tone="pending"
          title="Nothing waiting on review"
          description={
            status === "in_review"
              ? "Extraction candidates land here after the validate stage. Start a run without dry run to produce some."
              : "No candidates match this filter."
          }
        />
      ) : (
        <ul className="space-y-2">
          {candidates.map((candidate) => (
            <CandidateRow key={candidate.id} candidate={candidate} />
          ))}
        </ul>
      )}
    </>
  );
}

function FilterRow<T extends string>({
  label,
  options,
  active,
  onChange,
}: {
  label: string;
  options: readonly (T | null)[];
  active: T | null;
  onChange: (value: T | null) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-2xs uppercase tracking-wide text-faint">{label}</span>
      <div className="flex flex-wrap gap-1">
        {options.map((option) => (
          <button
            key={option ?? "all"}
            type="button"
            onClick={() => onChange(option)}
            aria-pressed={active === option}
            className={cn(
              "rounded border px-1.5 py-0.5 text-2xs transition-colors",
              active === option
                ? "border-accent/50 bg-accent/10 text-accent"
                : "border-line bg-raised text-muted hover:text-ink",
            )}
          >
            {option ? titleCase(option) : "All"}
          </button>
        ))}
      </div>
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: ExtractionCandidate }) {
  const review = useReviewCandidate();
  const toast = useToast();
  const [notes, setNotes] = useState("");
  const [showNotes, setShowNotes] = useState(false);

  const errors = candidate.issues.filter((issue) => issue.severity === "error");
  const warnings = candidate.issues.filter((issue) => issue.severity === "warning");
  const title = payloadTitle(candidate.payload) ?? truncateMiddle(candidate.id, 28);

  async function decide(decision: ReviewDecision) {
    try {
      await review.mutateAsync({
        id: candidate.id,
        decision,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });
      toast.push({
        tone: decision === "reject" ? "info" : "ok",
        title: `Candidate ${decision === "request_changes" ? "sent back" : `${decision}d`}`,
        message: title,
      });
      setNotes("");
      setShowNotes(false);
    } catch (mutationError) {
      toast.push({ tone: "error", title: "Review failed", message: describeError(mutationError).message });
    }
  }

  return (
    <Card as="li">
      <CardHeader
        title={title}
        subtitle={
          <>
            {titleCase(candidate.target)} · {candidate.chunk_ids.length} source{" "}
            {candidate.chunk_ids.length === 1 ? "chunk" : "chunks"} · extracted by {candidate.provenance.generator}{" "}
            {relativeTime(candidate.provenance.generated_at)}
          </>
        }
        actions={
          <>
            {candidate.duplicate_of ? (
              <Badge tone="warn" title={`Looks like a duplicate of ${candidate.duplicate_of}`}>
                Duplicate
              </Badge>
            ) : null}
            <Badge
              tone={candidate.confidence >= 0.8 ? "ok" : candidate.confidence >= 0.5 ? "warn" : "danger"}
              title="Extractor confidence: a high score is not an approval"
            >
              {formatPercent(candidate.confidence)}
            </Badge>
            <Badge tone={candidate.status === "approved" ? "ok" : "neutral"}>{titleCase(candidate.status)}</Badge>
          </>
        }
      />
      <CardBody className="space-y-2 py-pad-sm">
        {candidate.issues.length > 0 ? (
          <ul className="space-y-1">
            {candidate.issues.map((issue, index) => (
              <IssueLine key={`${issue.code}-${index}`} issue={issue} />
            ))}
          </ul>
        ) : (
          <p className="text-2xs text-faint">Validation raised no issues.</p>
        )}

        <details>
          <summary className="cursor-pointer text-2xs text-muted hover:text-ink">Payload</summary>
          <pre className="mt-1 max-h-64 overflow-auto rounded border border-line bg-canvas p-2 font-mono text-2xs leading-relaxed text-muted">
            {JSON.stringify(candidate.payload, null, 2)}
          </pre>
        </details>

        {showNotes ? (
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            rows={2}
            placeholder="What needs to change? The note is stored on the candidate's provenance."
            className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-2xs text-ink placeholder:text-faint focus:border-accent/50"
          />
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            loading={review.isPending}
            disabled={errors.length > 0}
            title={errors.length > 0 ? "Resolve the validation errors before approving" : undefined}
            onClick={() => decide("approve")}
          >
            <Check className="size-3.5" aria-hidden />
            Approve
          </Button>
          <Button variant="outline" loading={review.isPending} onClick={() => decide("request_changes")}>
            <MessageSquare className="size-3.5" aria-hidden />
            Request changes
          </Button>
          <Button variant="danger" loading={review.isPending} onClick={() => decide("reject")}>
            <X className="size-3.5" aria-hidden />
            Reject
          </Button>
          <button
            type="button"
            onClick={() => setShowNotes((open) => !open)}
            className="text-2xs text-muted underline-offset-2 hover:text-ink hover:underline"
          >
            {showNotes ? "Hide note" : "Add a note"}
          </button>
          {warnings.length > 0 && errors.length === 0 ? (
            <span className="ml-auto text-2xs text-warn">
              {warnings.length} warning{warnings.length === 1 ? "" : "s"}: approvable, but read them first
            </span>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function IssueLine({ issue }: { issue: ValidationIssue }) {
  const tone =
    issue.severity === "error" ? "text-danger" : issue.severity === "warning" ? "text-warn" : "text-info";
  return (
    <li className={cn("flex items-start gap-1.5 text-2xs", tone)}>
      <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
      <span>
        <span className="font-mono">{issue.code}</span> {issue.message}
        {issue.pointer ? <span className="ml-1 font-mono text-faint">at {issue.pointer}</span> : null}
      </span>
    </li>
  );
}

/**
 * Candidate payloads are shaped by their extraction target, so there is no
 * common title field to rely on, so try the usual keys and fall back to the id.
 */
function payloadTitle(payload: Record<string, unknown>): string | null {
  for (const key of ["title", "name", "prompt", "question"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return truncateMiddle(value.trim(), 90);
  }
  return null;
}
