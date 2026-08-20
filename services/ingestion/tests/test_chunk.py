"""Chunking.

Two invariants matter here and both are about citability. A chunk is what a concept
points at, so a chunk that begins mid-sentence or contains half a code sample makes
the citation useless — and a broken citation is worse than a missing one, because a
learner follows it and finds text that does not support the claim.
"""

from __future__ import annotations

from learnos_schema.ingestion import ParsedDocument

from learnos_ingestion.hashing import content_hash
from learnos_ingestion.stages.chunk import _protect_fences, _restore_fences, _sections, chunk_document


def parsed(text: str) -> ParsedDocument:
    return ParsedDocument(
        id="parsed.1",
        document_id="doc.1",
        source_id="test.source",
        title="Test",
        text=text,
        content_hash=content_hash(text),
    )


class TestSections:
    def test_builds_a_cumulative_heading_path(self) -> None:
        text = (
            "# Health checks\n\n"
            "Intro prose that is long enough to survive the minimum length filter "
            "and then some more words after it.\n\n"
            "## Timeouts\n\n"
            "A timeout that is shorter than the upstream's p99 will fail a healthy target.\n"
        )
        sections = _sections(text)
        paths = [path for path, _ in sections]
        assert ["Health checks"] in paths
        # The nested section carries its parent, which is what the UI renders as a
        # breadcrumb on a citation.
        assert ["Health checks", "Timeouts"] in paths

    def test_a_deeper_heading_pops_back_out(self) -> None:
        text = "# A\n\nbody a\n\n## B\n\nbody b\n\n# C\n\nbody c\n"
        paths = [path for path, _ in _sections(text)]
        assert ["C"] in paths
        assert ["A", "C"] not in paths

    def test_preamble_before_the_first_heading_survives(self) -> None:
        """Docs pages routinely open with a paragraph before any heading. Dropping it
        loses the one sentence that says what the page is about."""
        sections = _sections("Opening paragraph.\n\n# Heading\n\nbody\n")
        assert sections[0][0] == []
        assert "Opening paragraph." in sections[0][1]

    def test_unheaded_text_is_one_section(self) -> None:
        assert _sections("just prose") == [([], "just prose")]


class TestFenceProtection:
    def test_round_trips(self) -> None:
        body = "before\n\n```python\nx = 1\n```\n\nafter"
        protected, placeholders = _protect_fences(body)
        assert "```" not in protected
        assert _restore_fences(protected, placeholders) == body

    def test_multiple_fences_are_independent(self) -> None:
        body = "```\na\n```\n\ntext\n\n```\nb\n```"
        protected, placeholders = _protect_fences(body)
        assert len(placeholders) == 2
        assert _restore_fences(protected, placeholders) == body


class TestChunkDocument:
    def test_prepends_the_heading_path_into_the_text(self) -> None:
        """Not merely stored alongside — *in* the text.

        Search runs over the text. A chunk about retry behaviour that never repeats
        the word "retry" because it sat under a "## Retries" heading is a chunk that
        is unfindable by the exact query it answers.
        """
        text = "# Retries\n\n" + ("The backoff multiplier controls how quickly attempts spread out. " * 8)
        chunks = chunk_document(parsed(text), subject_id="s.x")
        assert chunks
        assert chunks[0].text.startswith("Retries\n\n")
        assert chunks[0].heading_path == ["Retries"]

    def test_never_splits_a_code_fence(self) -> None:
        """An oversized chunk is inefficient; a bisected code sample is wrong.

        The fence below is far larger than the target, so a naive splitter would cut
        it. Every emitted chunk must contain an even number of fence markers.
        """
        fence = "```python\n" + "\n".join(f"line_{index} = {index}" for index in range(400)) + "\n```"
        text = f"# Example\n\nSome prose introducing it.\n\n{fence}\n\nTrailing prose after the block.\n"
        chunks = chunk_document(parsed(text), subject_id="s.x", target_tokens=200, overlap_tokens=20)
        for chunk in chunks:
            assert chunk.text.count("```") % 2 == 0, "a code fence was split across chunks"

    def test_drops_stubs_too_small_to_cite(self) -> None:
        text = "# See also\n\nRefs.\n\n# Real section\n\n" + ("Substantial explanatory prose here. " * 12)
        chunks = chunk_document(parsed(text), subject_id="s.x")
        assert all(len(chunk.text) >= 80 for chunk in chunks)
        assert not any(chunk.heading_path == ["See also"] for chunk in chunks)

    def test_ordinals_are_contiguous_from_zero(self) -> None:
        """The chunk id includes the ordinal, so a gap would make two runs over the
        same document mint different ids for identical text."""
        text = "\n\n".join(f"## Section {index}\n\n" + ("Prose. " * 40) for index in range(6))
        chunks = chunk_document(parsed(text), subject_id="s.x", target_tokens=200, overlap_tokens=20)
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))

    def test_is_deterministic(self) -> None:
        text = "# A\n\n" + ("Words that go on for a while and then keep going. " * 30)
        first = chunk_document(parsed(text), subject_id="s.x", target_tokens=300, overlap_tokens=30)
        second = chunk_document(parsed(text), subject_id="s.x", target_tokens=300, overlap_tokens=30)
        assert [chunk.id for chunk in first] == [chunk.id for chunk in second]

    def test_overlap_carries_context_forward(self) -> None:
        """Without overlap, a sentence straddling a boundary lands in neither chunk's
        searchable text."""
        paragraphs = [f"Paragraph {index} explaining something at length. " * 6 for index in range(12)]
        text = "# A\n\n" + "\n\n".join(paragraphs)
        chunks = chunk_document(parsed(text), subject_id="s.x", target_tokens=300, overlap_tokens=150)
        assert len(chunks) > 1
        # Some tail of chunk n reappears at the head of chunk n+1.
        tail = chunks[0].text.strip().split("\n\n")[-1]
        assert tail in chunks[1].text
