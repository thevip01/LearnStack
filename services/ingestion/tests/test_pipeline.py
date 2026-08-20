"""The orchestrator's refusals.

The pipeline's own logic is thin — it wires stages and records reports. What is worth
testing is the three things it will not do: run stages it was not asked for, write
anything on a dry run, or treat ``publish`` as a step it can take.
"""

from __future__ import annotations

import json
from pathlib import Path

from learnos_ingestion.config import IngestionSettings
from learnos_ingestion.pipeline import DEFAULT_STAGES, STAGE_ORDER, Pipeline, PipelineResult
from learnos_schema.ingestion import StageReport

from .conftest import FakeRepo


class FakeSession:
    """Only ``commit`` is ever called on a session by the pipeline itself."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def pipeline_with(repo: FakeRepo, settings: IngestionSettings) -> tuple[Pipeline, FakeSession]:
    session = FakeSession()
    pipeline = Pipeline(session, settings=settings)  # type: ignore[arg-type]
    pipeline.repo = repo  # type: ignore[assignment]
    return pipeline, session


class TestStageOrder:
    def test_build_is_not_in_the_default_span(self) -> None:
        """``build`` writes learner-visible content and needs approved candidates,
        which cannot exist on the same pass that first proposes them. A human stands
        between extract and build, always."""
        assert "build" not in DEFAULT_STAGES
        assert DEFAULT_STAGES[-1] == "validate"

    def test_publish_is_not_a_stage(self) -> None:
        """Content goes live when an admin reloads the registry from disk. If publishing
        were a stage, a scheduled crawl could put unreviewed content in front of
        learners without anyone deciding to."""
        assert "publish" not in STAGE_ORDER
        assert "publish" not in DEFAULT_STAGES

    def test_default_stages_are_a_prefix_of_the_order(self) -> None:
        assert STAGE_ORDER[: len(DEFAULT_STAGES)] == DEFAULT_STAGES


class TestSpan:
    def test_fills_the_gap_between_requested_stages(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        """Requesting fetch and extract runs everything between them.

        Honouring the request literally would extract from whatever stale chunks
        happened to be stored, producing candidates that cite text the source no longer
        contains — the exact failure this pipeline exists to prevent.
        """
        pipeline, _ = pipeline_with(repo, settings)
        assert pipeline._span(("fetch", "extract")) == {"fetch", "parse", "clean", "chunk", "embed", "extract"}

    def test_a_single_stage_is_just_itself(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        """Re-extracting from stored chunks after fixing a prompt must not re-crawl."""
        pipeline, _ = pipeline_with(repo, settings)
        assert pipeline._span(("extract",)) == {"extract"}
        assert pipeline._span(("build",)) == {"build"}

    def test_order_of_the_request_does_not_matter(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        pipeline, _ = pipeline_with(repo, settings)
        assert pipeline._span(("extract", "fetch")) == pipeline._span(("fetch", "extract"))

    def test_an_unrecognised_stage_falls_back_to_the_default(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """Not an error, and deliberately not an empty span: a typo that silently ran
        nothing would look like a successful no-op run."""
        pipeline, _ = pipeline_with(repo, settings)
        assert pipeline._span(("publish",)) == set(DEFAULT_STAGES)
        assert pipeline._span(()) == set(DEFAULT_STAGES)


class TestRun:
    async def test_no_sources_fails_the_run_with_a_next_step(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """An empty crawl that reports success is indistinguishable from a subject whose
        sources were never registered, so this says which it is and what to do."""
        pipeline, _ = pipeline_with(repo, settings)

        result = await pipeline.run("programming.python")

        assert not result.ok
        assert len(result.stages) == 1
        assert "sources sync" in result.stages[0].messages[0]

    async def test_a_dry_run_writes_nothing(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        """No run row, no stage rows, no commits. The default has to be genuinely
        consequence-free or nobody will trust it against an unaudited source."""
        pipeline, session = pipeline_with(repo, settings)

        await pipeline.run("programming.python", dry_run=True)

        assert repo.stages == []
        assert session.commits == 0
        assert repo.published == []
        assert repo.deleted == []

    async def test_the_run_id_is_scoped_to_the_subject(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """Run ids show up in log lines and stage rows. One that does not name its
        subject makes a multi-subject deployment's logs unreadable."""
        pipeline, _ = pipeline_with(repo, settings)
        result = await pipeline.run("programming.python")
        assert result.run_id.startswith("run.programming.python.")

    async def test_two_runs_get_distinct_ids_within_the_same_second(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """The timestamp has second resolution, so the uuid suffix is what stops two
        runs launched together from writing to the same row."""
        pipeline, _ = pipeline_with(repo, settings)
        first = await pipeline.run("programming.python")
        second = await pipeline.run("programming.python")
        assert first.run_id != second.run_id

    async def test_an_exception_becomes_a_failed_report_not_a_traceback(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """A crawl that dies halfway must still produce a report an operator can read,
        including the stages that had already succeeded."""
        pipeline, _ = pipeline_with(repo, settings)

        async def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError("upstream went away")

        pipeline._execute = explode  # type: ignore[method-assign]
        result = await pipeline.run("programming.python")

        assert not result.ok
        assert "pipeline aborted: RuntimeError: upstream went away" in result.stages[0].messages[0]


class TestSubjectDir:
    def test_finds_a_package_by_its_manifest_id(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        """The manifest is the authority on which id a directory holds.

        Deriving ``subjects/programming/python`` from ``programming.python`` would break
        the first time someone reorganised the tree — and break silently, by building
        into a directory nobody reads.
        """
        directory = settings.subjects_dir / "anywhere" / "at" / "all"
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps({"id": "programming.python"}), encoding="utf-8")
        pipeline, _ = pipeline_with(repo, settings)

        assert pipeline._subject_dir("programming.python") == directory

    def test_accepts_the_legacy_subject_id_key(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        directory = settings.subjects_dir / "python"
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(
            json.dumps({"subject_id": "programming.python"}), encoding="utf-8"
        )
        pipeline, _ = pipeline_with(repo, settings)

        assert pipeline._subject_dir("programming.python") == directory

    def test_a_malformed_manifest_is_skipped_not_fatal(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """One package mid-edit must not make every other subject unbuildable."""
        broken = settings.subjects_dir / "broken"
        broken.mkdir(parents=True)
        (broken / "manifest.json").write_text("{not json", encoding="utf-8")
        good = settings.subjects_dir / "good"
        good.mkdir(parents=True)
        (good / "manifest.json").write_text(json.dumps({"id": "programming.python"}), encoding="utf-8")
        pipeline, _ = pipeline_with(repo, settings)

        assert pipeline._subject_dir("programming.python") == good

    def test_returns_none_when_the_root_is_absent(self, repo: FakeRepo, settings: IngestionSettings) -> None:
        pipeline, _ = pipeline_with(repo, settings)
        assert pipeline._subject_dir("programming.python") is None

    def test_returns_none_rather_than_the_wrong_package(
        self, repo: FakeRepo, settings: IngestionSettings
    ) -> None:
        """Falling back to the only package present would build Python content into a
        Cloud package."""
        directory = settings.subjects_dir / "cloud"
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps({"id": "cloud.aws"}), encoding="utf-8")
        pipeline, _ = pipeline_with(repo, settings)

        assert pipeline._subject_dir("programming.python") is None


class TestPipelineResult:
    def test_one_failed_stage_fails_the_run(self) -> None:
        result = PipelineResult(run_id="run.1", subject_id="s.x", dry_run=True)
        result.stages.append(StageReport(stage="fetch", items_out=3))
        assert result.ok
        result.stages.append(StageReport(stage="parse", ok=False, messages=["boom"]))
        assert not result.ok

    def test_a_run_with_no_stages_is_ok(self) -> None:
        """Vacuously — and that is why ``run`` always records at least one report."""
        assert PipelineResult(run_id="run.1", subject_id="s.x", dry_run=True).ok

    def test_the_summary_says_whether_it_was_live(self) -> None:
        """The single most important line in the output. An operator reading a report
        must never have to infer whether it was applied."""
        dry = PipelineResult(run_id="run.1", subject_id="s.x", dry_run=True).summary_lines()
        live = PipelineResult(run_id="run.1", subject_id="s.x", dry_run=False).summary_lines()
        assert any("DRY RUN" in line for line in dry)
        assert any("LIVE" in line for line in live)

    def test_the_summary_surfaces_stage_messages(self) -> None:
        result = PipelineResult(run_id="run.1", subject_id="s.x", dry_run=True)
        result.stages.append(StageReport(stage="clean", ok=False, messages=["under 5% of bytes survived"]))
        text = "\n".join(result.summary_lines())
        assert "FAIL" in text
        assert "under 5% of bytes survived" in text
