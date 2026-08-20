"""Extraction and the build stage.

The two places where generated content could leak past a human. Every test here
asserts a refusal or a cap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from learnos_schema.ingestion import ExtractionRequest, ExtractionTarget

from learnos_ingestion.extractors import resolve
from learnos_ingestion.extractors.stub import MAX_CONFIDENCE, StubExtractor
from learnos_ingestion.stages.build import build_package, next_version
from learnos_ingestion.stages.extract import validate_candidate

from .conftest import FakeCandidateRow, make_chunk

SECTION = (
    "Closures and late binding\n\n"
    "A closure captures the variable itself rather than its value at definition time. "
    "You must not rely on the value a name held when the lambda was written, because the "
    "lookup happens when the closure is called. This is the single most common source of "
    "surprise in loops that build a list of callables, and it never behaves the way a "
    "reader expects on first encounter. The fix is to bind the value explicitly as a "
    "default argument, which is evaluated once at definition time.\n\n"
    "```python\n"
    "makers = [lambda i=i: i * 2 for i in range(3)]\n"
    "print([maker() for maker in makers])\n"
    "```\n"
)


def request_for(target: str, *, existing: list[str] | None = None) -> ExtractionRequest:
    return ExtractionRequest(
        subject_id="programming.python",
        target=target,
        chunks=[make_chunk(SECTION, heading_path=["Functions", "Closures and late binding"])],
        existing_ids=existing or [],
    )


class TestStubExtractor:
    async def test_produces_a_schema_valid_concept(self) -> None:
        candidates = await StubExtractor().extract(request_for(ExtractionTarget.CONCEPT.value))
        assert candidates
        assert not [
            issue
            for candidate in candidates
            for issue in validate_candidate(candidate)
            if issue.severity == "error"
        ], "the stub must produce payloads that pass the real schema, or the review queue is noise"

    async def test_is_deterministic(self) -> None:
        """Two runs over unchanged text must produce identical candidate ids, or every
        refresh floods the review queue with re-proposals of content already there."""
        first = await StubExtractor().extract(request_for(ExtractionTarget.CONCEPT.value))
        second = await StubExtractor().extract(request_for(ExtractionTarget.CONCEPT.value))
        assert [candidate.id for candidate in first] == [candidate.id for candidate in second]

    async def test_confidence_is_capped_below_the_looks_vetted_line(self) -> None:
        """Nothing generated may look like it has been checked.

        0.55 sits below the 0.6 an operator would read as "probably fine". No prompt
        and no source structure can push it higher.
        """
        candidates = await StubExtractor().extract(request_for(ExtractionTarget.CONCEPT.value))
        assert all(candidate.confidence <= MAX_CONFIDENCE for candidate in candidates)
        assert MAX_CONFIDENCE < 0.6

    async def test_citations_come_from_the_chunks_that_were_read(self) -> None:
        """The extractor builds citations from chunk ids in its own code. A generated
        citation would send a learner to a page that does not support the claim."""
        chunk = make_chunk(SECTION, heading_path=["Functions", "Closures and late binding"])
        candidates = await StubExtractor().extract(
            ExtractionRequest(subject_id="programming.python", target="concept", chunks=[chunk])
        )
        assert candidates
        assert candidates[0].chunk_ids == [chunk.id]
        assert candidates[0].payload["sources"][0]["content_hash"] == chunk.content_hash

    async def test_provenance_names_the_generator(self) -> None:
        candidates = await StubExtractor().extract(request_for(ExtractionTarget.CONCEPT.value))
        assert candidates[0].provenance.generator == StubExtractor.name

    async def test_an_existing_id_becomes_a_duplicate_flag_not_a_silent_skip(self) -> None:
        """A source that now says something about an existing concept is usually a
        signal the concept needs updating — a reviewer has to see it."""
        candidates = await StubExtractor().extract(
            request_for(ExtractionTarget.CONCEPT.value, existing=["programming.python.closures-and-late-binding"])
        )
        assert candidates
        assert candidates[0].duplicate_of == "programming.python.closures-and-late-binding"
        assert candidates[0].confidence < 0.3

    async def test_practice_is_a_schema_valid_quiz(self) -> None:
        """The payload must satisfy the real discriminated union, not resemble it.

        ``PracticeTask`` has no "predict output" kind — the shape is a quiz holding one
        short-answer question. A payload with an invented ``kind`` validates against
        nothing and can never be approved.
        """
        candidates = await StubExtractor().extract(request_for(ExtractionTarget.PRACTICE.value))
        assert candidates
        payload = candidates[0].payload
        assert payload["kind"] == "quiz"
        assert payload["questions"][0]["type"] == "short_answer"
        assert not [issue for issue in validate_candidate(candidates[0]) if issue.severity == "error"]

    async def test_practice_leaves_the_answer_key_empty_and_says_so(self) -> None:
        """The accepted answers must come from a real sandbox run, never from a guess.

        The error issue is what keeps the task out of ``is_promotable``, so a question
        with no answer key cannot reach a learner. It has to be the extractor's own
        issue because an empty ``answer`` list is schema-valid — nothing downstream
        would otherwise notice.
        """
        candidates = await StubExtractor().extract(request_for(ExtractionTarget.PRACTICE.value))
        assert candidates
        candidate = candidates[0]
        assert candidate.payload["questions"][0]["answer"] == []
        codes = {issue.code for issue in candidate.issues if issue.severity == "error"}
        assert "answer_key_empty" in codes

    async def test_a_concept_carries_the_generator_into_the_payload(self) -> None:
        """The payload is what the build stage writes to disk. A concept file with no
        generator on it is indistinguishable from hand-authored content."""
        candidates = await StubExtractor().extract(request_for(ExtractionTarget.CONCEPT.value))
        assert candidates[0].payload["provenance"]["generator"] == StubExtractor.name
        assert candidates[0].payload["provenance"]["status"] == "draft"

    async def test_an_empty_purpose_is_flagged_rather_than_invented(self) -> None:
        """``purpose`` is required by the schema and an empty string satisfies it,
        which is exactly why it needs a warning attached."""
        text = "Widgets\n\n" + ("A widget has three fields and a name. " * 12)
        chunk = make_chunk(text, heading_path=["Reference", "Widgets"])
        candidates = await StubExtractor().extract(
            ExtractionRequest(subject_id="programming.python", target="concept", chunks=[chunk])
        )
        assert candidates
        assert candidates[0].payload["purpose"] == ""
        assert "purpose_not_derivable" in {issue.code for issue in candidates[0].issues}

    async def test_declines_targets_it_cannot_judge(self) -> None:
        """A plausible-looking skeleton a reviewer must read to discover is worthless
        costs more than an empty queue."""
        for target in (ExtractionTarget.PROJECT.value, ExtractionTarget.ASSESSMENT.value):
            assert await StubExtractor().extract(request_for(target)) == []

    async def test_skips_a_chunk_with_no_heading(self) -> None:
        request = ExtractionRequest(
            subject_id="programming.python", target="concept", chunks=[make_chunk(SECTION, heading_path=[])]
        )
        assert await StubExtractor().extract(request) == []


class TestResolve:
    def test_stub_needs_no_key(self) -> None:
        assert resolve("stub", model=None, api_key=None).name.startswith("stub")

    def test_an_unknown_name_fails_loudly(self) -> None:
        """Falling back to the stub would produce a run that looks successful while
        quietly generating far worse content than the operator asked for."""
        with pytest.raises((ValueError, KeyError, LookupError)):
            resolve("wishful", model=None, api_key=None)


class TestNextVersion:
    def test_bumps_the_patch_within_the_month(self) -> None:
        from datetime import datetime, timezone

        today = datetime(2026, 8, 19, tzinfo=timezone.utc)
        assert next_version("2026.08.0", today=today) == "2026.08.1"
        assert next_version("2026.08.9", today=today) == "2026.08.10"

    def test_rolls_over_into_a_new_month(self) -> None:
        from datetime import datetime, timezone

        today = datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert next_version("2026.08.4", today=today) == "2026.09.0"

    def test_survives_a_hand_edited_version(self) -> None:
        """Manifests are edited by hand. A malformed version must not crash a build."""
        from datetime import datetime, timezone

        today = datetime(2026, 8, 19, tzinfo=timezone.utc)
        assert next_version("not-a-version", today=today) == "2026.08.0"


def write_manifest(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"id": "programming.python", "version": "2026.08.0", "concepts_dir": "concepts"}),
        encoding="utf-8",
    )


def candidate_row(payload_id: str = "programming.python.closures") -> FakeCandidateRow:
    return FakeCandidateRow(
        id=f"cand.{payload_id}",
        subject_id="programming.python",
        target="concept",
        payload={"id": payload_id, "title": "Closures"},
        status="approved",
    )


class TestBuildPackage:
    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        write_manifest(tmp_path)
        result, report = build_package(subject_dir=tmp_path, candidates=[candidate_row()], dry_run=True)
        assert result.written == ["cand.programming.python.closures"]
        assert not (tmp_path / "concepts").exists()
        assert report.ok

    def test_parks_rather_than_overwriting_a_hand_edited_file(self, tmp_path: Path) -> None:
        """Automatic merging of generated content over authored content is how a
        platform loses a week of authoring to a crawl nobody was watching."""
        write_manifest(tmp_path)
        concepts = tmp_path / "concepts"
        concepts.mkdir()
        existing = concepts / "programming.python.closures.json"
        existing.write_text('{"id": "programming.python.closures", "title": "Hand edited"}', encoding="utf-8")

        result, report = build_package(subject_dir=tmp_path, candidates=[candidate_row()], dry_run=False)

        assert result.parked == ["cand.programming.python.closures"]
        assert result.written == []
        assert json.loads(existing.read_text(encoding="utf-8"))["title"] == "Hand edited"
        assert (concepts / "programming.python.closures.incoming.json").is_file()
        assert any("rather than overwriting" in message for message in report.messages)

    def test_a_missing_manifest_is_an_error_not_a_silent_skip(self, tmp_path: Path) -> None:
        result, report = build_package(subject_dir=tmp_path, candidates=[candidate_row()], dry_run=True)
        assert not result.ok
        assert not report.ok

    def test_a_candidate_without_a_payload_id_is_reported(self, tmp_path: Path) -> None:
        write_manifest(tmp_path)
        broken = candidate_row()
        broken.payload = {"title": "no id"}
        result, _ = build_package(subject_dir=tmp_path, candidates=[broken], dry_run=True)
        assert result.errors

    def test_curriculum_targets_are_skipped_not_written(self, tmp_path: Path) -> None:
        """Folding a generated fragment into curriculum.json would reorder a human's
        module ordering."""
        write_manifest(tmp_path)
        row = candidate_row()
        row.target = "curriculum"
        result, report = build_package(subject_dir=tmp_path, candidates=[row], dry_run=True)
        assert result.skipped == [row.id]
        assert any("by hand" in message for message in report.messages)

    def test_version_is_not_bumped_when_nothing_was_written(self, tmp_path: Path) -> None:
        write_manifest(tmp_path)
        result, _ = build_package(subject_dir=tmp_path, candidates=[], dry_run=True)
        assert result.version_after in (None, "2026.08.0")
