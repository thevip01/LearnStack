"""The orchestrator.

Wires the stages together, threads one database session through them, and records a
``StageReport`` per stage as it completes. Everything interesting about this module
is in what it refuses to do.

**A run defaults to a dry run.** ``dry_run=True`` means every stage computes its
result and reports it, and nothing is written — no rows, no raw bodies, no package
files. An operator can therefore always ask "what would a refresh of this source
do?" and get a real answer with no consequences. The default is not a safety net
bolted on; it is what makes the pipeline usable against sources nobody has audited
yet.

**Stages are requested, not implied.** Asking for ``chunk`` does not silently run
``fetch``. The stages are ordered and a run executes the contiguous span it was
asked for, using stored state for anything earlier. That is what lets an operator
re-extract from chunks already on disk after fixing a prompt, without re-crawling.

**``publish`` is not a stage.** ``build`` writes the package; there is no step after
it that flips content live, because content goes live when the API reloads from disk
and that is an explicit admin action.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog
from learnos_schema.ingestion import (
    Chunk,
    ExtractionCandidate,
    IngestionRun,
    ParsedDocument,
    SourceSpec,
    StageReport,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .config import IngestionSettings, get_settings
from .diffing import DiffSummary, diff_run
from .extractors import resolve as resolve_extractor
from .stages import (
    BuildResult,
    clean_report,
    run_build,
    run_chunk,
    run_embed,
    run_extract,
    run_fetch,
    run_parse,
    run_validate,
)
from .storage import IngestionRepository, RawStore

log = structlog.get_logger(__name__)

#: Canonical order. Index in this tuple is what "contiguous span" means.
STAGE_ORDER = ("fetch", "parse", "clean", "chunk", "embed", "extract", "validate", "build")

#: What a bare ``run`` does. ``build`` is excluded: it writes learner-visible content
#: and requires approved candidates, which cannot exist on the same pass that first
#: proposes them. A human stands between extract and build, always.
DEFAULT_STAGES = ("fetch", "parse", "clean", "chunk", "embed", "extract", "validate")


@dataclass
class PipelineResult:
    run_id: str
    subject_id: str
    dry_run: bool
    stages: list[StageReport] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    parsed: list[ParsedDocument] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    candidates: list[ExtractionCandidate] = field(default_factory=list)
    diff: DiffSummary | None = None
    build: BuildResult | None = None

    @property
    def ok(self) -> bool:
        return all(report.ok for report in self.stages)

    def summary_lines(self) -> list[str]:
        lines = [
            f"run {self.run_id}",
            f"subject {self.subject_id}  sources {len(self.sources)}  {'DRY RUN' if self.dry_run else 'LIVE'}",
            "",
        ]
        for report in self.stages:
            mark = "ok " if report.ok else "FAIL"
            lines.append(
                f"  [{mark}] {str(report.stage):9s} in={report.items_in:<5d} out={report.items_out:<5d} "
                f"skipped={report.skipped}"
            )
            for message in report.messages:
                lines.append(f"           - {message}")
        if self.diff is not None:
            lines.append("")
            lines.extend(f"  {line}" for line in self.diff.describe())
        return lines


class Pipeline:
    """One run, one session, one subject."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: IngestionSettings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session
        self.repo = IngestionRepository(session)
        self.store = RawStore(self.settings.raw_dir)

    def _span(self, stages: tuple[str, ...]) -> set[str]:
        """The contiguous span of stages to execute.

        Requesting ``fetch`` and ``extract`` runs everything between them, because
        extract needs chunks and chunks come from parse. Honouring the request
        literally would mean extracting from whatever stale chunks happened to be
        stored, which produces candidates that cite text the source no longer
        contains — the exact failure this pipeline exists to avoid.
        """
        indices = [STAGE_ORDER.index(stage) for stage in stages if stage in STAGE_ORDER]
        if not indices:
            return set(DEFAULT_STAGES)
        return set(STAGE_ORDER[min(indices) : max(indices) + 1])

    async def run(
        self,
        subject_id: str,
        *,
        source_ids: list[str] | None = None,
        stages: tuple[str, ...] = DEFAULT_STAGES,
        dry_run: bool = True,
        subject_dir: Path | None = None,
    ) -> PipelineResult:
        active = self._span(stages)
        run_id = f"run.{subject_id}.{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.{uuid.uuid4().hex[:8]}"
        result = PipelineResult(run_id=run_id, subject_id=subject_id, dry_run=dry_run)

        specs: list[SourceSpec] = await self.repo.sources_for(subject_id, source_ids)
        result.sources = [spec.id for spec in specs]

        if not dry_run:
            await self.repo.create_run(
                IngestionRun(
                    id=run_id,
                    subject_id=subject_id,
                    source_ids=result.sources,
                    dry_run=dry_run,
                    status="running",
                )
            )
            await self.session.commit()

        log.info(
            "pipeline.start",
            run=run_id,
            subject=subject_id,
            sources=len(specs),
            stages=sorted(active, key=STAGE_ORDER.index),
            dry_run=dry_run,
        )

        try:
            await self._execute(result, specs, active, subject_id, dry_run, subject_dir)
        except Exception as exc:  # noqa: BLE001
            result.stages.append(
                StageReport(stage="fetch", ok=False, messages=[f"pipeline aborted: {type(exc).__name__}: {exc}"])
            )
            if not dry_run:
                await self.repo.finish_run(run_id, "failed")
                await self.session.commit()
            log.exception("pipeline.failed", run=run_id)
            return result

        if not dry_run:
            await self.repo.finish_run(run_id, "succeeded" if result.ok else "failed")
            await self.session.commit()

        return result

    async def _execute(
        self,
        result: PipelineResult,
        specs: list[SourceSpec],
        active: set[str],
        subject_id: str,
        dry_run: bool,
        subject_dir: Path | None,
    ) -> None:
        raw_bytes = 0
        outcomes: dict = {}

        async def record(report: StageReport) -> None:
            report.finished_at = datetime.now(timezone.utc)
            result.stages.append(report)
            if not dry_run:
                await self.repo.append_stage(result.run_id, report)
                await self.session.commit()

        # -- fetch ----------------------------------------------------------
        if "fetch" in active:
            if not specs:
                await record(
                    StageReport(
                        stage="fetch",
                        ok=False,
                        messages=[
                            f"no enabled sources for subject {subject_id!r}. "
                            f"Register them with 'learnos-ingest sources sync' or via the admin API."
                        ],
                    )
                )
                return
            outcomes, report = await run_fetch(
                specs, repo=self.repo, store=self.store, settings=self.settings, dry_run=dry_run
            )
            await record(report)
            result.diff = await diff_run(outcomes, subject_id=subject_id, repo=self.repo)

            # Deletions are applied here, not in the fetch stage, because `removable`
            # is only trustworthy once the whole crawl has finished without error.
            if not dry_run:
                removed = 0
                for source_id, outcome in outcomes.items():
                    removed += await self.repo.delete_documents(outcome.removable)
                if removed:
                    await record(
                        StageReport(
                            stage="fetch",
                            items_in=removed,
                            items_out=0,
                            messages=[f"deleted {removed} documents no longer present at their source"],
                        )
                    )
                await self.session.commit()

        # -- parse / clean --------------------------------------------------
        if "parse" in active:
            pending: list[tuple[str, str, str, bytes, str | None]] = []
            if outcomes:
                for spec in specs:
                    outcome = outcomes.get(spec.id)
                    if outcome is None:
                        continue
                    for document in outcome.touched:
                        body = self.store.get(document.content_hash)
                        if body is None:
                            # Dry runs never wrote the body. Re-reading it here would
                            # mean a second fetch of every page purely to report what
                            # parse would do, so the stage reports the gap instead.
                            continue
                        raw_bytes += len(body)
                        pending.append(
                            (document.id, document.source_id, document.media_type, body, document.url)
                        )
            else:
                # No fetch this run: parse whatever is stored but unparsed.
                for spec in specs:
                    for row in await self.repo.documents_for(spec.id):
                        if row.text:
                            continue
                        body = self.store.get(row.content_hash)
                        if body is None:
                            continue
                        raw_bytes += len(body)
                        pending.append((row.id, row.source_id, row.media_type, body, row.url))

            if dry_run and not pending and outcomes:
                await record(
                    StageReport(
                        stage="parse",
                        skipped=sum(len(outcome.touched) for outcome in outcomes.values()),
                        messages=[
                            "dry run: bodies were not stored, so there is nothing to parse. "
                            "Run with --commit to see parse and downstream stages."
                        ],
                    )
                )
            else:
                result.parsed, report = await run_parse(pending, repo=self.repo, dry_run=dry_run)
                await record(report)
                if not dry_run:
                    await self.session.commit()

            if "clean" in active:
                await record(clean_report(result.parsed, raw_bytes))

        # -- chunk ----------------------------------------------------------
        if "chunk" in active:
            if result.parsed:
                result.chunks, report = await run_chunk(
                    result.parsed,
                    subject_id=subject_id,
                    repo=self.repo,
                    target_tokens=self.settings.chunk_target_tokens,
                    overlap_tokens=self.settings.chunk_overlap_tokens,
                    dry_run=dry_run,
                )
                await record(report)
                if not dry_run:
                    await self.session.commit()
            else:
                result.chunks = await self.repo.chunks_for(subject_id, source_ids=result.sources or None)
                await record(
                    StageReport(
                        stage="chunk",
                        items_in=0,
                        items_out=len(result.chunks),
                        messages=[f"nothing newly parsed; using {len(result.chunks)} stored chunks"],
                    )
                )

        # -- embed ----------------------------------------------------------
        if "embed" in active:
            await record(await run_embed(result.chunks, repo=self.repo, model=None, dry_run=dry_run))

        # -- extract / validate ---------------------------------------------
        if "extract" in active:
            ready, detail = self.settings.extractor_ready()
            if not ready:
                await record(StageReport(stage="extract", ok=False, messages=[detail]))
                return
            extractor = resolve_extractor(
                self.settings.extractor,
                model=self.settings.extractor_model,
                api_key=self.settings.extractor_api_key,
            )
            result.candidates, report = await run_extract(
                result.chunks,
                subject_id=subject_id,
                extractor=extractor,
                repo=self.repo,
                settings=self.settings,
                dry_run=dry_run,
            )
            report.messages.insert(0, f"extractor: {detail}")
            await record(report)

        if "validate" in active and result.candidates:
            result.candidates, report = await run_validate(
                result.candidates, repo=self.repo, dry_run=dry_run
            )
            await record(report)
            if not dry_run:
                await self.session.commit()

        # -- build ----------------------------------------------------------
        if "build" in active:
            directory = subject_dir or self._subject_dir(subject_id)
            if directory is None:
                await record(
                    StageReport(
                        stage="build",
                        ok=False,
                        messages=[f"no package directory found for {subject_id!r} under {self.settings.subjects_dir}"],
                    )
                )
                return
            result.build, report = await run_build(
                subject_id=subject_id, subject_dir=directory, repo=self.repo, dry_run=dry_run
            )
            await record(report)
            if not dry_run:
                await self.session.commit()

    def _subject_dir(self, subject_id: str) -> Path | None:
        """Locate a package by reading manifests rather than guessing a path.

        A subject id is dotted (``programming.python``) and the directory layout is
        nested (``subjects/programming/python``), but the two are not required to
        correspond — the manifest is the authority on which id a directory holds.
        Deriving the path from the id would break the first time someone reorganised
        the directory tree, and break silently, by building into a new directory
        nobody reads.
        """
        import json

        root = self.settings.subjects_dir
        if not root.is_dir():
            return None
        for manifest_path in sorted(root.rglob("manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("subject_id") == subject_id or payload.get("id") == subject_id:
                return manifest_path.parent
        return None
