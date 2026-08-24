"""The admin side of ingestion: sources, runs, candidates, provenance.

This module is the HTTP-facing half of a pipeline that lives in
``services/ingestion``. It owns none of the pipeline's semantics: it registers
sources, records runs, and moves candidates through review. The extractor behind
it is a stub in this phase, which is exactly why the review and provenance surface
exists now rather than later: the moment an LLM starts writing curriculum, the
question that matters is "where did this sentence come from", and an admin API
retrofitted onto an already-published package cannot answer it.

Two rules the routes depend on:

* **Approving is not publishing.** ``review`` moves a candidate to ``approved``
  and stops. Writing an approved candidate into the package directory and bumping
  the version is a separate build step, because a review that mutates live content
  is a review nobody can undo.
* **A run defaults to a dry run.** Anything that writes has to say so explicitly.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

import sqlalchemy as sa
from learnos_schema import LifecycleStatus, Provenance, SourceRef
from learnos_schema.ingestion import (
    ExtractionCandidate,
    ExtractionTarget,
    IngestionRun as IngestionRunModel,
    SourceSpec,
    StageReport,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import BadRequest, Conflict, NotFound
from ...logging import get_logger
from ...models import IngestionCandidate, IngestionChunk, IngestionDocument, IngestionRun, IngestionSource
from ...schemas.admin import ProvenanceChainStepOut, ProvenanceTrailOut

log = get_logger(__name__)

#: The stages a manually triggered run is allowed to ask for. ``publish`` is
#: absent: publishing is the build step, not something an HTTP call does.
RUNNABLE_STAGES = ("fetch", "parse", "clean", "chunk", "embed", "extract", "validate")

#: Review decision -> ``LifecycleStatus``.
#:
#: Two choices worth defending. ``request_changes`` lands back in ``draft`` rather
#: than a fourth state, so "needs work" and "not looked at yet" are the same queue
#: and nothing gets stranded in a status with no owner. And ``reject`` maps to
#: ``deprecated`` because ``LifecycleStatus`` is shared with published content,
#: where "rejected" is meaningless: adding a synonym to an enum that governs
#: ``Provenance.is_learner_visible`` for one caller's vocabulary is a worse trade
#: than reusing the terminal state. ``is_promotable`` already treats anything
#: outside approved/published as unpublishable, so the behaviour is identical.
DECISION_STATUS: dict[str, LifecycleStatus] = {
    "approve": LifecycleStatus.APPROVED,
    "reject": LifecycleStatus.DEPRECATED,
    "request_changes": LifecycleStatus.DRAFT,
}

#: What ``target`` may be filtered on. Read off the enum so a new extraction target
#: is filterable the day it is added.
CANDIDATE_TARGETS = tuple(item.value for item in ExtractionTarget)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def source_row_to_dict(row: IngestionSource) -> dict[str, Any]:
    """Row -> ``SourceSpec``-shaped dict.

    Round-tripped through the schema model rather than hand-built so that a field
    added to ``SourceSpec`` appears in the API without an edit here, and so a row
    that has drifted out of shape fails loudly at the boundary.
    """
    return SourceSpec(
        id=row.id,
        subject_id=row.subject_id,
        title=row.title,
        adapter=row.adapter,  # type: ignore[arg-type]
        source_type=row.source_type,  # type: ignore[arg-type]
        entrypoint=row.entrypoint,
        priority=row.priority,
        is_first_party=row.is_first_party,
        license=row.license,
        policy=row.policy or {},  # type: ignore[arg-type]
        enabled=row.enabled,
        last_run_at=row.last_run_at,
        notes=row.notes,
    ).model_dump(mode="json")


async def list_sources(session: AsyncSession, *, subject_id: str | None = None) -> list[dict[str, Any]]:
    stmt = sa.select(IngestionSource)
    if subject_id:
        stmt = stmt.where(IngestionSource.subject_id == subject_id)
    result = await session.execute(stmt.order_by(IngestionSource.priority.desc(), IngestionSource.id))
    return [source_row_to_dict(row) for row in result.scalars()]


async def upsert_source(session: AsyncSession, spec: SourceSpec) -> dict[str, Any]:
    """Create or replace a source.

    Upsert rather than create-only: a source id is content-meaningful (it names
    the thing being ingested), so re-posting one with a corrected rate limit is the
    normal editing gesture and a 409 there would just push operators into deleting
    rows to fix typos.
    """
    row = await session.get(IngestionSource, spec.id)
    if row is None:
        row = IngestionSource(id=spec.id)
        session.add(row)

    row.subject_id = spec.subject_id
    row.title = spec.title
    row.adapter = str(spec.adapter)
    row.source_type = str(spec.source_type)
    row.entrypoint = spec.entrypoint
    row.priority = spec.priority
    row.is_first_party = spec.is_first_party
    row.license = spec.license
    row.policy = spec.policy.model_dump(mode="json")
    row.enabled = spec.enabled
    row.notes = spec.notes
    await session.flush()
    log.info("ingestion_source_upserted", source_id=spec.id, subject_id=spec.subject_id)
    return source_row_to_dict(row)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def run_row_to_dict(row: IngestionRun) -> dict[str, Any]:
    return IngestionRunModel(
        id=row.id,
        subject_id=row.subject_id,
        source_ids=list(row.source_ids or []),
        target_version=row.target_version,
        dry_run=row.dry_run,
        stages=[StageReport.model_validate(stage) for stage in (row.stages or [])],
        started_at=row.started_at,
        finished_at=row.finished_at,
        status=row.status,  # type: ignore[arg-type]
    ).model_dump(mode="json")


async def list_runs(session: AsyncSession, *, subject_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    stmt = sa.select(IngestionRun)
    if subject_id:
        stmt = stmt.where(IngestionRun.subject_id == subject_id)
    result = await session.execute(stmt.order_by(IngestionRun.started_at.desc()).limit(limit))
    return [run_row_to_dict(row) for row in result.scalars()]


async def get_run(session: AsyncSession, run_id: str) -> dict[str, Any]:
    row = await session.get(IngestionRun, run_id)
    if row is None:
        raise NotFound(f"unknown ingestion run {run_id!r}")
    return run_row_to_dict(row)


async def create_run(
    session: AsyncSession,
    *,
    subject_id: str,
    source_ids: Sequence[str] | None,
    stages: Sequence[str] | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Record a requested run.

    The row is written ``status="running"`` with an empty stage list and the
    pipeline fills it in. Nothing is executed here: the API process must not fetch
    the internet or call an extractor, both because it would block a request thread
    for minutes and because a service that answers learner traffic has no business
    holding outbound credentials.

    A run with no runnable stage is refused rather than recorded as a no-op, since a
    row that claims to have run and did nothing is worse than an error.
    """
    requested = [stage.strip().lower() for stage in (stages or RUNNABLE_STAGES) if stage.strip()]
    unknown = [stage for stage in requested if stage not in RUNNABLE_STAGES]
    if unknown:
        raise BadRequest(
            "unknown or non-runnable ingestion stage",
            {"unknown_stages": unknown, "runnable": list(RUNNABLE_STAGES)},
        )
    if not requested:
        raise BadRequest("a run must name at least one stage")

    known = await list_sources(session, subject_id=subject_id)
    known_ids = {item["id"] for item in known}
    chosen = list(source_ids) if source_ids else sorted(known_ids)
    missing = [item for item in chosen if item not in known_ids]
    if missing:
        raise NotFound(
            "unknown source id for this subject",
            {"unknown_source_ids": missing, "subject_id": subject_id},
        )
    if not chosen:
        raise Conflict(
            f"no ingestion sources are registered for {subject_id!r}",
            {"reason": "no_sources"},
        )

    run_id = f"run.{subject_id}.{_now():%Y%m%dT%H%M%S}.{uuid.uuid4().hex[:8]}"
    row = IngestionRun(
        id=run_id,
        subject_id=subject_id,
        source_ids=chosen,
        dry_run=dry_run,
        stages=[],
        started_at=_now(),
        status="running",
    )
    session.add(row)
    await session.flush()
    log.info(
        "ingestion_run_requested",
        run_id=run_id,
        subject_id=subject_id,
        dry_run=dry_run,
        stages=requested,
        sources=len(chosen),
    )
    return run_row_to_dict(row)


# ---------------------------------------------------------------------------
# Candidates and review
# ---------------------------------------------------------------------------


def candidate_row_to_dict(row: IngestionCandidate) -> dict[str, Any]:
    return ExtractionCandidate(
        id=row.id,
        subject_id=row.subject_id,
        target=row.target,  # type: ignore[arg-type]
        payload=dict(row.payload or {}),
        chunk_ids=list(row.chunk_ids or []),
        confidence=row.confidence,
        issues=list(row.issues or []),  # type: ignore[arg-type]
        duplicate_of=row.duplicate_of,
        provenance=Provenance.model_validate(row.provenance or {}),
        status=row.status,  # type: ignore[arg-type]
    ).model_dump(mode="json")


async def list_candidates(
    session: AsyncSession,
    *,
    subject_id: str | None = None,
    status: str | None = None,
    target: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = sa.select(IngestionCandidate)
    if subject_id:
        stmt = stmt.where(IngestionCandidate.subject_id == subject_id)
    if status:
        stmt = stmt.where(IngestionCandidate.status == status)
    if target:
        stmt = stmt.where(IngestionCandidate.target == target)
    # Lowest confidence first: the review queue exists for the cases the extractor
    # was unsure about, and sorting by recency buries them.
    result = await session.execute(
        stmt.order_by(IngestionCandidate.confidence.asc(), IngestionCandidate.id).limit(limit)
    )
    return [candidate_row_to_dict(row) for row in result.scalars()]


async def review_candidate(
    session: AsyncSession,
    candidate_id: str,
    *,
    decision: str,
    notes: str | None,
    payload: dict[str, Any] | None,
    reviewer: str,
) -> dict[str, Any]:
    """Record a human decision on one candidate.

    An edited ``payload`` replaces the extractor's, and the edit is *attributed*:
    ``generator`` becomes ``human-edited:<original>``. Silently accepting a
    reviewer's rewrite as model output would make the provenance trail a fiction,
    and the trail is the whole reason this table stores provenance at all.

    The update goes through the ``Provenance`` model rather than mutating the JSON
    blob because ``Provenance`` forbids extra keys: a stray ``human_edited`` field
    written straight into the column would parse fine on the way in and then throw
    on every subsequent read of the candidate.
    """
    row = await session.get(IngestionCandidate, candidate_id)
    if row is None:
        raise NotFound(f"unknown candidate {candidate_id!r}")

    new_status = DECISION_STATUS.get(decision)
    if new_status is None:  # pragma: no cover - the schema constrains this
        raise BadRequest(f"unknown review decision {decision!r}", {"allowed": sorted(DECISION_STATUS)})
    if row.status == LifecycleStatus.PUBLISHED.value:
        raise Conflict(
            "this candidate has already been published; edit the package instead",
            {"reason": "candidate_published"},
        )

    provenance = Provenance.model_validate(row.provenance or {})
    update: dict[str, Any] = {
        "reviewed_by": reviewer,
        "reviewed_at": _now(),
        "status": new_status,
    }
    if notes:
        update["notes"] = notes[:4_000]
    if payload is not None:
        row.payload = payload
        update["generator"] = _mark_human_edited(provenance.generator)

    row.provenance = provenance.model_copy(update=update).model_dump(mode="json")
    row.status = new_status.value
    await session.flush()
    log.info(
        "ingestion_candidate_reviewed",
        candidate_id=candidate_id,
        decision=decision,
        status=row.status,
        edited=payload is not None,
    )
    return candidate_row_to_dict(row)


def _mark_human_edited(generator: str) -> str:
    """Stamp a generator string as human-touched, idempotently.

    Idempotent because a candidate can be edited twice, and
    ``human-edited:human-edited:llm:x`` tells a reviewer nothing the single prefix
    did not already say.
    """
    return generator if generator.startswith("human-edited:") else f"human-edited:{generator}"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


async def provenance_trail(session: AsyncSession, entity_id: str) -> ProvenanceTrailOut:
    """Walk source -> document -> chunk -> candidate -> entity for one id.

    Answers "where did this statement come from" in one request. Built by walking
    backwards from the candidate that produced the entity, because forward links
    do not exist: a published concept records its provenance, not its children.
    """
    candidate = await _candidate_for_entity(session, entity_id)
    if candidate is None:
        raise NotFound(
            f"no ingestion provenance recorded for {entity_id!r}",
            {"reason": "hand_authored_or_unknown"},
        )

    provenance = Provenance.model_validate(candidate.provenance or {})
    chain: list[ProvenanceChainStepOut] = []

    chunk_ids = list(candidate.chunk_ids or [])
    chunks: list[IngestionChunk] = []
    if chunk_ids:
        result = await session.execute(sa.select(IngestionChunk).where(IngestionChunk.id.in_(chunk_ids)))
        chunks = list(result.scalars())

    document_ids = sorted({chunk.document_id for chunk in chunks})
    documents: list[IngestionDocument] = []
    if document_ids:
        result = await session.execute(
            sa.select(IngestionDocument).where(IngestionDocument.id.in_(document_ids))
        )
        documents = list(result.scalars())

    source_ids = sorted({doc.source_id for doc in documents} | {chunk.source_id for chunk in chunks})
    sources: list[IngestionSource] = []
    if source_ids:
        result = await session.execute(sa.select(IngestionSource).where(IngestionSource.id.in_(source_ids)))
        sources = list(result.scalars())

    for source in sources:
        chain.append(
            ProvenanceChainStepOut(
                stage="source",
                id=source.id,
                label=source.title,
                detail=source.entrypoint,
            )
        )
    for document in documents:
        chain.append(
            ProvenanceChainStepOut(
                stage="document",
                id=document.id,
                label=document.title or document.url or document.id,
                detail=document.canonical_url or document.url,
            )
        )
    for chunk in sorted(chunks, key=lambda item: (item.document_id, item.ordinal)):
        chain.append(
            ProvenanceChainStepOut(
                stage="chunk",
                id=chunk.id,
                label=" > ".join(chunk.heading_path) or f"chunk {chunk.ordinal}",
                detail=_excerpt(chunk.text),
            )
        )
    chain.append(
        ProvenanceChainStepOut(
            stage="candidate",
            id=candidate.id,
            label=f"{candidate.target} candidate ({candidate.status})",
            detail=f"confidence {candidate.confidence:.2f}",
        )
    )
    chain.append(
        ProvenanceChainStepOut(
            stage="published",
            id=entity_id,
            label=entity_id,
            detail=None,
        )
    )

    return ProvenanceTrailOut(
        entity_id=entity_id,
        entity_kind=str(candidate.target),
        provenance=provenance,
        # ``SourceRef`` has no licence field (licensing is a property of the source
        # registry, not of a citation), so the reference carries the identity and
        # the admin follows ``source_id`` back to the row for terms.
        sources=[
            SourceRef(
                source_id=source.id,
                title=source.title,
                url=source.entrypoint if source.entrypoint.startswith("http") else None,
                source_type=source.source_type,  # type: ignore[arg-type]
                retrieved_at=source.last_run_at,
            )
            for source in sources
        ],
        chain=chain,
    )


async def _candidate_for_entity(session: AsyncSession, entity_id: str) -> IngestionCandidate | None:
    """Find the candidate that became ``entity_id``.

    Tried in two ways because candidate ids are content-derived and the mapping is
    not guaranteed to be an equality: the direct id first, then a scan for a
    payload whose ``id`` matches. The scan is bounded to published and approved
    candidates, which is the only set that can have produced live content.
    """
    direct = await session.get(IngestionCandidate, entity_id)
    if direct is not None:
        return direct

    result = await session.execute(
        sa.select(IngestionCandidate)
        .where(IngestionCandidate.status.in_(["approved", "published"]))
        .order_by(IngestionCandidate.updated_at.desc())
        .limit(2_000)
    )
    for row in result.scalars():
        if str((row.payload or {}).get("id") or "") == entity_id:
            return row
    return None


def _excerpt(text: str, limit: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def candidate_id_for(subject_id: str, target: str, payload_id: str) -> str:
    """Deterministic candidate id.

    Content-derived so that re-extracting the same entity from the same source
    updates one row instead of accumulating near-duplicates in the review queue.
    Exposed here rather than in the pipeline because the admin API and the pipeline
    must agree on it, and this package is the one both can import.
    """
    digest = hashlib.sha256(f"{subject_id}|{target}|{payload_id}".encode()).hexdigest()[:16]
    return f"cand.{subject_id}.{target}.{digest}"
