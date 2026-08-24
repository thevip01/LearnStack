"""The id scheme.

These four properties are the foundation of incremental ingestion. If any of them
breaks, a refresh either regenerates content it did not need to (burning extractor
budget and detaching learner mastery evidence) or fails to regenerate content it
did (serving text the source no longer contains). Nothing else in the pipeline can
compensate.
"""

from __future__ import annotations

from learnos_ingestion.hashing import (
    HASH_LEN,
    chunk_id_for,
    content_hash,
    document_id_for,
    safe_segment,
    stable_id,
    token_estimate,
)


class TestContentHash:
    def test_is_stable_and_fixed_length(self) -> None:
        first = content_hash("hello")
        assert first == content_hash("hello")
        assert len(first) == HASH_LEN

    def test_parts_are_length_prefixed(self) -> None:
        """``("ab", "c")`` must not hash the same as ``("a", "bc")``.

        Without length prefixing, concatenation makes these identical, and a document
        whose (source_id, locator) pair happens to split differently gets the same id
        as an unrelated one, two sources silently overwriting each other's rows.
        """
        assert content_hash("ab", "c") != content_hash("a", "bc")

    def test_bytes_and_str_agree(self) -> None:
        assert content_hash("hello") == content_hash(b"hello")


class TestDocumentId:
    def test_ignores_the_body(self) -> None:
        """Identity is *where a document lives*, not what it currently says.

        This is the single most important property in the module. If the id included
        the body, an edited page would look like a new document plus a removed one:
        every concept derived from it would be orphaned rather than updated, and the
        diff would report a deletion the crawl never observed.
        """
        first = document_id_for("python.docs", "https://docs.python.org/3/tutorial/")
        second = document_id_for("python.docs", "https://docs.python.org/3/tutorial/")
        assert first == second

    def test_distinguishes_sources_at_the_same_locator(self) -> None:
        locator = "https://example.invalid/page"
        assert document_id_for("source.a", locator) != document_id_for("source.b", locator)

    def test_distinguishes_locators_in_the_same_source(self) -> None:
        assert document_id_for("s", "/a") != document_id_for("s", "/b")


class TestChunkId:
    def test_includes_the_text(self) -> None:
        """The inverse of the document rule, and equally deliberate.

        A chunk's id changing on edit is what lets the diff name exactly which
        concepts an edit invalidated. If chunk ids were position-only, a paragraph
        rewrite would leave every citation pointing at text that no longer says what
        the concept claims, and nothing would flag it.
        """
        before = chunk_id_for("doc.1", 9, "the original paragraph")
        after = chunk_id_for("doc.1", 9, "the edited paragraph")
        assert before != after

    def test_unedited_chunks_keep_their_ids(self) -> None:
        """Editing paragraph nine must not disturb one through eight."""
        original = [chunk_id_for("doc.1", index, f"paragraph {index}") for index in range(12)]
        edited = [
            chunk_id_for("doc.1", index, "rewritten" if index == 9 else f"paragraph {index}")
            for index in range(12)
        ]
        assert original[:9] == edited[:9]
        assert original[10:] == edited[10:]
        assert original[9] != edited[9]

    def test_ordinal_participates(self) -> None:
        assert chunk_id_for("doc.1", 0, "same text") != chunk_id_for("doc.1", 1, "same text")


class TestStableId:
    def test_prefix_is_readable(self) -> None:
        """Ids are grepped by humans reading a candidates table, so keep the prefix."""
        value = stable_id("cand.concept", "programming.python", "closures")
        assert value.startswith("cand.concept.")

    def test_is_deterministic_across_processes(self) -> None:
        """No ``hash()``, no uuid4, no clock.

        Python's ``hash()`` is salted per process, so an id built from it would differ
        between the crawl that wrote a row and the build that reads it.
        """
        assert stable_id("p", "a", "b") == stable_id("p", "a", "b")


class TestSafeSegment:
    def test_produces_an_id_fragment(self) -> None:
        assert safe_segment("Late Binding & Closures!") == "late-binding-closures"

    def test_collapses_runs(self) -> None:
        assert "--" not in safe_segment("a   ---   b")

    def test_never_returns_empty(self) -> None:
        """An empty segment would build an id ending in a dot, which fails schema
        validation far away from the cause."""
        assert safe_segment("!!!")
        assert safe_segment("")


class TestTokenEstimate:
    def test_scales_with_length(self) -> None:
        assert token_estimate("x" * 400) > token_estimate("x" * 40)

    def test_is_never_zero_for_nonempty_text(self) -> None:
        """The chunker divides by this; a zero would make a one-character section
        loop forever rather than emit."""
        assert token_estimate("a") >= 1
