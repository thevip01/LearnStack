"""The invalidation chain.

``document -> chunk -> candidate -> concept``. This is the reason incremental
ingestion is worth building at all: a refresh must regenerate only what actually
changed, because the alternative replaces content that learners already have mastery
evidence attached to.

The two properties that carry the design are asserted here: an unchanged paragraph
invalidates nothing, and an incomplete crawl invalidates nothing at all.
"""

from __future__ import annotations

from learnos_schema.ingestion import RawDocument

from learnos_ingestion.diffing import diff_for_source, diff_run
from learnos_ingestion.hashing import document_id_for
from learnos_ingestion.stages.fetch import FetchOutcome

from .conftest import FakeCandidateRow, FakeRepo, make_chunk

SUBJECT = "programming.python"
SOURCE = "test.source"


def raw(locator: str, body: str) -> RawDocument:
    return RawDocument(
        id=document_id_for(SOURCE, locator),
        source_id=SOURCE,
        path=locator,
        media_type="text/markdown",
        content_hash=f"hash-of-{body}",
        byte_size=len(body),
    )


def seed(repo: FakeRepo, *, document_id: str, texts: list[str]) -> list[str]:
    """Store chunks for a document and a concept candidate citing each one."""
    chunk_ids: list[str] = []
    for ordinal, text in enumerate(texts):
        chunk = make_chunk(text, ordinal=ordinal, document_id=document_id, source_id=SOURCE, subject_id=SUBJECT)
        repo.chunks.append(chunk)
        chunk_ids.append(chunk.id)
        repo.candidates.append(
            FakeCandidateRow(
                id=f"cand.{chunk.id}",
                subject_id=SUBJECT,
                target="concept",
                payload={"id": f"{SUBJECT}.concept-{ordinal}"},
                chunk_ids=[chunk.id],
                status="published",
            )
        )
    return chunk_ids


class TestDiffForSource:
    async def test_nothing_changed_invalidates_nothing(self, repo: FakeRepo) -> None:
        document = raw("a.md", "body")
        seed(repo, document_id=document.id, texts=["Paragraph one. " * 12])
        outcome = FetchOutcome(unchanged=[document.id])

        diff = await diff_for_source(SOURCE, outcome, subject_id=SUBJECT, repo=repo)

        assert diff.is_empty
        assert diff.affected_concepts == []

    async def test_a_changed_document_names_the_concepts_derived_from_it(self, repo: FakeRepo) -> None:
        """This is the whole point.

        Not "the source changed, re-extract everything" but "these three concepts cite
        text that no longer exists".
        """
        document = raw("a.md", "v2")
        seed(repo, document_id=document.id, texts=["First. " * 12, "Second. " * 12])
        outcome = FetchOutcome(changed=[document])

        diff = await diff_for_source(SOURCE, outcome, subject_id=SUBJECT, repo=repo)

        assert sorted(diff.affected_concepts) == [f"{SUBJECT}.concept-0", f"{SUBJECT}.concept-1"]
        assert diff.changed_documents == [document.id]

    async def test_a_sibling_document_is_untouched(self, repo: FakeRepo) -> None:
        """A one-page edit must not invalidate the rest of the source. Chunk ids
        include their text, so the blast radius is exactly the pages that moved."""
        changed = raw("a.md", "v2")
        untouched = raw("b.md", "v1")
        seed(repo, document_id=changed.id, texts=["Changed page. " * 12])
        seed(repo, document_id=untouched.id, texts=["Stable page. " * 12])

        diff = await diff_for_source(SOURCE, FetchOutcome(changed=[changed]), subject_id=SUBJECT, repo=repo)

        assert len(diff.affected_concepts) == 1

    async def test_practice_and_concepts_are_reported_separately(self, repo: FakeRepo) -> None:
        """Different consequences. An invalidated concept needs rewriting; an
        invalidated practice task may need its answer key re-derived from a run."""
        document = raw("a.md", "v2")
        chunk_ids = seed(repo, document_id=document.id, texts=["Text. " * 12])
        repo.candidates.append(
            FakeCandidateRow(
                id="cand.practice.1",
                subject_id=SUBJECT,
                target="practice",
                payload={"id": f"practice.{SUBJECT}.abc123"},
                chunk_ids=chunk_ids,
                status="published",
            )
        )

        diff = await diff_for_source(SOURCE, FetchOutcome(changed=[document]), subject_id=SUBJECT, repo=repo)

        assert diff.affected_concepts == [f"{SUBJECT}.concept-0"]
        assert diff.affected_practice == [f"practice.{SUBJECT}.abc123"]

    async def test_a_truncated_crawl_invalidates_nothing_through_removal(self, repo: FakeRepo) -> None:
        """A rate-limited run that stopped at ``max_pages`` has not proven anything is
        gone. Treating ``missing`` as removal here is how a slow crawl silently
        destroys half a subject."""
        document = raw("a.md", "v1")
        seed(repo, document_id=document.id, texts=["Text. " * 12])
        outcome = FetchOutcome(missing=[document.id], truncated=True)

        diff = await diff_for_source(SOURCE, outcome, subject_id=SUBJECT, repo=repo)

        assert diff.removed_documents == []
        assert diff.affected_concepts == []

    async def test_an_errored_crawl_also_refuses_to_remove(self, repo: FakeRepo) -> None:
        document = raw("a.md", "v1")
        seed(repo, document_id=document.id, texts=["Text. " * 12])
        outcome = FetchOutcome(missing=[document.id], errors=["connection reset"])

        diff = await diff_for_source(SOURCE, outcome, subject_id=SUBJECT, repo=repo)

        assert diff.removed_documents == []

    async def test_a_clean_crawl_does_report_removal(self, repo: FakeRepo) -> None:
        """A page genuinely deleted from the docs site must invalidate the concepts
        derived from it, or the platform teaches a feature that no longer exists."""
        document = raw("a.md", "v1")
        seed(repo, document_id=document.id, texts=["Text. " * 12])
        outcome = FetchOutcome(missing=[document.id])

        diff = await diff_for_source(SOURCE, outcome, subject_id=SUBJECT, repo=repo)

        assert diff.removed_documents == [document.id]
        assert diff.affected_concepts == [f"{SUBJECT}.concept-0"]

    async def test_a_candidate_with_no_payload_id_is_skipped_not_crashed_on(self, repo: FakeRepo) -> None:
        """The candidates table deliberately holds content that fails validation,
        including payloads with no id."""
        document = raw("a.md", "v2")
        chunk_ids = seed(repo, document_id=document.id, texts=["Text. " * 12])
        repo.candidates.append(
            FakeCandidateRow(
                id="cand.broken",
                subject_id=SUBJECT,
                target="concept",
                payload={"title": "no id"},
                chunk_ids=chunk_ids,
            )
        )

        diff = await diff_for_source(SOURCE, FetchOutcome(changed=[document]), subject_id=SUBJECT, repo=repo)

        assert diff.affected_concepts == [f"{SUBJECT}.concept-0"]


class TestDiffSummary:
    async def test_deduplicates_across_sources(self, repo: FakeRepo) -> None:
        """Two sources can support the same concept.

        A concept citing both the language reference and a tutorial is the normal case,
        not an edge case. Reporting it once per source would make an operator think
        twice as much broke as did.
        """
        document = raw("a.md", "v2")
        primary = make_chunk("Shared text. " * 12, document_id=document.id, source_id=SOURCE, subject_id=SUBJECT)
        secondary = make_chunk(
            "Shared text. " * 12, ordinal=1, document_id=document.id, source_id="other.source", subject_id=SUBJECT
        )
        repo.chunks.extend([primary, secondary])
        repo.candidates.append(
            FakeCandidateRow(
                id="cand.shared",
                subject_id=SUBJECT,
                target="concept",
                payload={"id": f"{SUBJECT}.shared-concept"},
                chunk_ids=[primary.id, secondary.id],
                status="published",
            )
        )
        outcomes = {SOURCE: FetchOutcome(changed=[document]), "other.source": FetchOutcome(changed=[document])}

        summary = await diff_run(outcomes, subject_id=SUBJECT, repo=repo)

        assert [diff.affected_concepts for diff in summary.diffs] == [
            [f"{SUBJECT}.shared-concept"],
            [f"{SUBJECT}.shared-concept"],
        ]
        assert summary.affected_concepts == [f"{SUBJECT}.shared-concept"]

    async def test_describes_an_unchanged_source_explicitly(self, repo: FakeRepo) -> None:
        """"unchanged" and "we never looked" must not read the same in a report."""
        summary = await diff_run({SOURCE: FetchOutcome()}, subject_id=SUBJECT, repo=repo)
        assert summary.is_empty
        assert summary.describe() == [f"{SOURCE}: unchanged"]

    async def test_truncates_a_long_invalidation_list(self, repo: FakeRepo) -> None:
        document = raw("a.md", "v2")
        seed(repo, document_id=document.id, texts=[f"Paragraph {index}. " * 12 for index in range(10)])

        summary = await diff_run({SOURCE: FetchOutcome(changed=[document])}, subject_id=SUBJECT, repo=repo)

        line = next(line for line in summary.describe() if "invalidates concepts" in line)
        assert "+4 more" in line
