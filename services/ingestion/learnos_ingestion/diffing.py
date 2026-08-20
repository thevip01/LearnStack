"""Change detection: what a refresh invalidated.

This module answers the question that makes incremental ingestion worth building:
when a source changes, *which* concepts and practice tasks are now suspect? The
naive answer — all of them — means every refresh regenerates the whole subject,
which burns extractor budget and, far worse, replaces content that learners have
mastery evidence attached to.

The chain is ``document -> chunk -> candidate -> concept``. Chunk ids include their
text, so an edit to one paragraph changes exactly one chunk id, and the candidates
citing that chunk id are exactly the content that edit invalidated. Everything else
in the document is untouched and stays untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from learnos_schema.ingestion import ExtractionTarget, SourceDiff

from .stages.fetch import FetchOutcome

log = structlog.get_logger(__name__)


@dataclass
class DiffSummary:
    """Human-readable rollup across every source in a run."""

    diffs: list[SourceDiff]

    @property
    def is_empty(self) -> bool:
        return all(diff.is_empty for diff in self.diffs)

    @property
    def affected_concepts(self) -> list[str]:
        seen: dict[str, None] = {}
        for diff in self.diffs:
            for concept_id in diff.affected_concepts:
                seen[concept_id] = None
        return list(seen)

    @property
    def affected_practice(self) -> list[str]:
        seen: dict[str, None] = {}
        for diff in self.diffs:
            for practice_id in diff.affected_practice:
                seen[practice_id] = None
        return list(seen)

    def describe(self) -> list[str]:
        lines: list[str] = []
        for diff in self.diffs:
            if diff.is_empty:
                lines.append(f"{diff.source_id}: unchanged")
                continue
            lines.append(
                f"{diff.source_id}: +{len(diff.added_documents)} added, "
                f"~{len(diff.changed_documents)} changed, -{len(diff.removed_documents)} removed"
            )
            if diff.affected_concepts:
                shown = ", ".join(diff.affected_concepts[:6])
                more = f" (+{len(diff.affected_concepts) - 6} more)" if len(diff.affected_concepts) > 6 else ""
                lines.append(f"  invalidates concepts: {shown}{more}")
            if diff.affected_practice:
                shown = ", ".join(diff.affected_practice[:6])
                more = f" (+{len(diff.affected_practice) - 6} more)" if len(diff.affected_practice) > 6 else ""
                lines.append(f"  invalidates practice: {shown}{more}")
        return lines


async def diff_for_source(
    source_id: str,
    outcome: FetchOutcome,
    *,
    subject_id: str,
    repo,  # IngestionRepository
) -> SourceDiff:
    """Turn a fetch outcome into a ``SourceDiff`` with affected content named.

    ``subject_id`` is passed in rather than derived from the outcome: ``RawDocument``
    carries a ``source_id`` but no subject, and the chunk table is indexed by
    subject. Inferring it would mean an extra query per source to answer something
    the caller already knows.
    """
    changed_ids = [document.id for document in outcome.changed]
    removed_ids = outcome.removable

    diff = SourceDiff(
        source_id=source_id,
        added_documents=[document.id for document in outcome.added],
        changed_documents=changed_ids,
        removed_documents=removed_ids,
    )

    invalidating = set(changed_ids) | set(removed_ids)
    if not invalidating:
        return diff

    # The chunks currently stored for these documents are the *old* chunks — the
    # replace happens later in the chunk stage. That ordering is what makes this
    # work: after replacement the old chunk ids are gone and the link from a
    # published concept back to the text it was derived from is unrecoverable.
    stale_chunks = [
        chunk.id
        for chunk in await repo.chunks_for(subject_id, source_ids=[source_id])
        if chunk.document_id in invalidating
    ]
    if not stale_chunks:
        return diff

    for candidate in await repo.candidates_citing(stale_chunks):
        payload_id = (candidate.payload or {}).get("id")
        if not isinstance(payload_id, str):
            continue
        if str(candidate.target) == ExtractionTarget.CONCEPT.value:
            diff.affected_concepts.append(payload_id)
        elif str(candidate.target) == ExtractionTarget.PRACTICE.value:
            diff.affected_practice.append(payload_id)

    log.info(
        "diff.computed",
        source=source_id,
        changed=len(changed_ids),
        removed=len(removed_ids),
        stale_chunks=len(stale_chunks),
        concepts=len(diff.affected_concepts),
        practice=len(diff.affected_practice),
    )
    return diff


async def diff_run(
    outcomes: dict[str, FetchOutcome],
    *,
    subject_id: str,
    repo,  # IngestionRepository
) -> DiffSummary:
    return DiffSummary(
        [
            await diff_for_source(source_id, outcome, subject_id=subject_id, repo=repo)
            for source_id, outcome in outcomes.items()
        ]
    )
