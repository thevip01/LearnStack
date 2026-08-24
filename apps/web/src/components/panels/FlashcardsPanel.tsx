"use client";

import { RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Markdown } from "@/components/content/Markdown";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { useNavItem } from "@/components/runtime/nav";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConcept } from "@/lib/queries";
import type { ConceptOut, TermBlock } from "@/lib/types";
import { cfgStringArray } from "@/lib/utils";

type CardKind = "term" | "definition" | "common_errors";
type Card = { kind: CardKind; front: string; back: string };

const KIND_LABEL: Record<CardKind, string> = { term: "term", definition: "definition", common_errors: "common error" };
const DEFAULT_DERIVE: CardKind[] = ["term", "definition", "common_errors"];

/** Turn a concept's authored content into review cards, honoring `derive_from`. */
function buildCards(concept: ConceptOut, deriveFrom: readonly string[]): Card[] {
  const cards: Card[] = [];
  if (deriveFrom.includes("term")) {
    for (const block of concept.body) {
      if (block.type === "term") {
        const term = block as TermBlock;
        cards.push({ kind: "term", front: term.term, back: term.definition_md });
      }
    }
  }
  if (deriveFrom.includes("definition")) {
    cards.push({ kind: "definition", front: `Define: ${concept.title}`, back: concept.definition });
  }
  if (deriveFrom.includes("common_errors")) {
    for (const error of concept.common_errors) {
      cards.push({ kind: "common_errors", front: error.error, back: `**Cause.** ${error.cause}\n\n**Fix.** ${error.fix}` });
    }
  }
  return cards;
}

/**
 * Spaced-style review over a concept's own terms, definition and common errors.
 *
 * There is no subject-specific card content here: every card is derived generically
 * from the concept's authored blocks. Grading is a local queue ("again" sends a
 * card to the back, the rest advance) and is intentionally not submitted anywhere.
 * Mastery is measured by graded practice, not by self-report, so these buttons only
 * sequence the deck.
 */
export function FlashcardsPanel({ runtime, nodeId, panel }: PanelProps) {
  const navItem = useNavItem(runtime, nodeId);
  const isConcept = navItem?.kind === "concept";
  const { data: concept, isLoading, error } = useConcept(runtime.id, isConcept ? nodeId : null);

  const deriveFrom = useMemo(() => {
    const configured = cfgStringArray(panel.config, "derive_from");
    return configured.length > 0 ? configured : DEFAULT_DERIVE;
  }, [panel.config]);
  const grades = useMemo(() => {
    const configured = cfgStringArray(panel.config, "grade_scale");
    return configured.length > 0 ? configured : ["again", "hard", "good", "easy"];
  }, [panel.config]);

  const cards = useMemo(() => (concept ? buildCards(concept, deriveFrom) : []), [concept, deriveFrom]);

  const [queue, setQueue] = useState<number[]>([]);
  const [revealed, setRevealed] = useState(false);
  const [reviewed, setReviewed] = useState(0);

  // Rebuild the deck whenever the concept (and therefore its cards) changes.
  useEffect(() => {
    setQueue(cards.map((_, index) => index));
    setRevealed(false);
    setReviewed(0);
  }, [concept?.id, cards.length]);

  if (!nodeId || !navItem) {
    return <PanelHint title="Nothing to review" description="Pick a concept to build a deck from its terms and pitfalls." />;
  }
  if (!isConcept) {
    return <PanelHint title="No cards here" description="Cards come from concepts. Open one to review it." />;
  }
  if (isLoading) return <PanelLoading label="Building deck" rows={5} />;
  if (error) return <PanelError error={error} />;
  if (cards.length === 0) {
    return <PanelHint title="No cards" description="This concept has no terms or common errors to review yet." />;
  }

  const restart = () => {
    setQueue(cards.map((_, index) => index));
    setRevealed(false);
    setReviewed(0);
  };

  // The queue holds indices into `cards`, and the effect that refills it runs
  // *after* the render in which a new concept's cards arrive, so for one frame the
  // head index can point past the end of the deck. Treating "no card at the head"
  // the same as "queue empty" covers both cases without asserting the index away.
  const head = queue[0];
  const current = head === undefined ? undefined : cards[head];

  if (!current) {
    return (
      <PanelBody className="grid place-items-center p-pad">
        <div className="space-y-3 text-center">
          <p className="text-sm font-medium text-ink">Deck complete</p>
          <p className="text-2xs text-faint">Reviewed {reviewed} cards.</p>
          <Button size="sm" variant="secondary" onClick={restart}>
            <RotateCcw className="size-3" aria-hidden />
            Review again
          </Button>
        </div>
      </PanelBody>
    );
  }

  const advance = (grade: string) => {
    setRevealed(false);
    if (grade === "again") {
      // Straight to the back of the queue, so the card comes round again.
      setQueue((q) => [...q.slice(1), ...q.slice(0, 1)]);
    } else {
      setQueue((q) => q.slice(1));
      setReviewed((r) => r + 1);
    }
  };

  return (
    <>
      <PanelToolbar>
        <Badge tone="neutral">{KIND_LABEL[current.kind]}</Badge>
        <span className="ml-auto text-2xs text-faint">
          {reviewed} done · {queue.length} left
        </span>
      </PanelToolbar>

      <PanelBody className="flex flex-col items-center gap-4 p-pad">
        <button
          type="button"
          onClick={() => setRevealed((value) => !value)}
          className="group flex min-h-44 w-full max-w-lg flex-col rounded-panel border border-line bg-surface p-5 text-left transition-colors hover:border-line-strong"
        >
          <span className="text-2xs uppercase tracking-wide text-faint">{revealed ? "Answer" : "Prompt (click to flip)"}</span>
          {revealed ? (
            <div className="mt-2 text-sm leading-relaxed text-ink">
              <Markdown>{current.back}</Markdown>
            </div>
          ) : (
            <div className="mt-2 flex flex-1 items-center">
              <span className="text-base font-medium text-ink">{current.front}</span>
            </div>
          )}
        </button>

        {revealed ? (
          <div className="flex w-full max-w-lg items-center justify-center gap-1.5">
            {grades.map((grade) => (
              <Button
                key={grade}
                size="sm"
                variant={grade === "again" ? "danger" : grade === "easy" ? "primary" : "secondary"}
                className="flex-1 capitalize"
                onClick={() => advance(grade)}
              >
                {grade}
              </Button>
            ))}
          </div>
        ) : (
          <p className="text-2xs text-faint">Recall the answer, then flip.</p>
        )}
      </PanelBody>
    </>
  );
}
