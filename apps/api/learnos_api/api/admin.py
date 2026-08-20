"""Admin surface: reload subjects, drive ingestion, read provenance.

Everything here sits behind ``CurrentAdmin``. Two of these routes are genuinely
dangerous — reload swaps the content every learner is reading, and a non-dry run
rewrites a package — so the guard is not decoration.

The division of labour with the ingestion service is strict. This router *records*
intent and *reads* results. It never fetches a URL, never calls a model, never
blocks a request thread on a crawl. A pipeline triggered inline would hold a worker
open for minutes and would put outbound network credentials in the process that
answers learner traffic; both are reasons enough on their own.

``POST /subjects/reload`` is the one exception to "the API does not do work": it
re-reads local disk, re-mirrors Redis and reindexes search. That is bounded,
local, and the only way to pick up an edited package without a restart.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status
from learnos_schema.ingestion import SourceSpec

from ..logging import get_logger
from ..modules.auth.deps import CurrentAdmin
from ..modules.knowledge import search as search_mod
from ..modules import ingestion_admin
from ..schemas.admin import (
    CandidateListOut,
    CandidateReviewIn,
    ProvenanceTrailOut,
    RunCreateIn,
    RunListOut,
    SourceListOut,
    SubjectLoadFailureOut,
    SubjectReloadOut,
    SubjectValidateOut,
)
from .deps import RegistryDep, SessionDep, resolve_subject

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@router.post("/subjects/reload", response_model=SubjectReloadOut)
async def reload_subjects(
    registry: RegistryDep,
    session: SessionDep,
    _: CurrentAdmin,
) -> SubjectReloadOut:
    """Re-read every package from disk, then re-mirror and reindex.

    Order matters: ``reload`` swaps the in-memory registry atomically, so the
    cache mirror and the search index are rebuilt from what actually loaded rather
    than from what was on disk a moment ago. A package that fails validation leaves
    the previously loaded version serving traffic and comes back in ``failed`` —
    a bad edit must not be able to empty the catalog.
    """
    report = await registry.reload()
    await registry.mirror_to_cache()

    indexed = 0
    for subject in registry.all_subjects():
        indexed += await search_mod.reindex_subject(session, subject.package, subject.content_hash)

    log.info(
        "admin_subjects_reloaded",
        loaded=report.loaded,
        failed=[failure.subject_id for failure in report.failed],
        indexed_rows=indexed,
    )
    return SubjectReloadOut(
        loaded=report.loaded,
        failed=[
            SubjectLoadFailureOut(id=failure.subject_id, problems=failure.problems)
            for failure in report.failed
        ],
    )


@router.get("/subjects/{subject_id}/validate", response_model=SubjectValidateOut)
async def validate_subject(
    subject_id: str,
    registry: RegistryDep,
    _: CurrentAdmin,
) -> SubjectValidateOut:
    """Re-run reference validation against the loaded package, plus soft checks.

    Problems are the same ones that would have refused the package at load; a
    loaded subject should therefore report none, and any that appear mean the
    validator and the loader have drifted apart.

    Warnings are the interesting half. They are the checks that must not block a
    package but do predict a broken learner experience — a skill nothing can
    measure, a concept with no practice attached, a hint ladder that jumps straight
    to the answer. Enforcing them would make authoring a subject impossible; hiding
    them would let a subject ship where mastery can never be earned.
    """
    subject = resolve_subject(registry, subject_id)
    package = subject.package

    problems = package.validate_references()
    warnings: list[str] = []

    if package.manifest.content_hash and package.manifest.content_hash != subject.content_hash:
        warnings.append(
            f"manifest content_hash {package.manifest.content_hash!r} does not match computed "
            f"{subject.content_hash!r}; the package was edited without a rebuild"
        )

    # A skill with no practice can never accumulate evidence, so its mastery is
    # pinned at whatever the concept dimension alone can reach. The dimension lives
    # on ``evaluation``, not the task: it is a property of how the task is scored.
    measured: dict[str, set[str]] = {}
    for task in package.practice.values():
        for skill_id in task.skills:
            measured.setdefault(skill_id, set()).add(str(task.evaluation.dimension))
    for skill in package.curriculum.skills:
        dimensions = measured.get(skill.id, set())
        if not dimensions:
            warnings.append(f"skill {skill.id!r} has no practice task; its mastery can never be measured")
        elif len(dimensions) == 1:
            warnings.append(
                f"skill {skill.id!r} is only measured on {sorted(dimensions)[0]!r}; "
                "overall mastery is capped until a second dimension has evidence"
            )

    for concept in package.concepts.values():
        if not concept.practice and not any(
            getattr(block, "type", None) == "embed_practice" for block in concept.body
        ):
            warnings.append(f"concept {concept.id!r} has no practice attached; it is reading with no doing")
        if not concept.sources:
            warnings.append(f"concept {concept.id!r} cites no source; its provenance cannot be shown")

    for task in package.practice.values():
        revealing = [hint for hint in task.hints if hint.reveals_solution]
        if len(task.hints) == 1 and revealing:
            warnings.append(
                f"practice {task.id!r} has a single solution-revealing hint; there is no ladder to climb"
            )
        if len(revealing) > 1:
            warnings.append(f"practice {task.id!r} marks {len(revealing)} hints as revealing the solution")

    for module in (module for track in package.curriculum.tracks for module in track.modules):
        if not module.concepts:
            warnings.append(f"module {module.id!r} contains no concepts")

    return SubjectValidateOut(problems=problems, warnings=warnings)


# ---------------------------------------------------------------------------
# Ingestion: sources
# ---------------------------------------------------------------------------


@router.get("/ingestion/sources", response_model=SourceListOut)
async def list_sources(
    session: SessionDep,
    _: CurrentAdmin,
    subject_id: str | None = Query(default=None),
) -> SourceListOut:
    return SourceListOut(sources=await ingestion_admin.list_sources(session, subject_id=subject_id))


@router.post("/ingestion/sources", response_model=SourceListOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    spec: SourceSpec,
    session: SessionDep,
    _: CurrentAdmin,
) -> SourceListOut:
    """Register or update one source.

    The body is a ``SourceSpec`` verbatim, so the schema's own rules apply at the
    edge: a source marked first-party with a priority under 80 is refused here
    rather than quietly letting a blog outrank official documentation.

    The response is the full list for the subject, not the single row, because the
    thing an operator needs to see after adding a source is where it now sits in
    the priority order.
    """
    await ingestion_admin.upsert_source(session, spec)
    return SourceListOut(sources=await ingestion_admin.list_sources(session, subject_id=spec.subject_id))


# ---------------------------------------------------------------------------
# Ingestion: runs
# ---------------------------------------------------------------------------


@router.post("/ingestion/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    body: RunCreateIn,
    session: SessionDep,
    _: CurrentAdmin,
) -> dict[str, Any]:
    """Record a run for the pipeline to pick up.

    202, never 200: the row is a request, and the stage reports arrive later. A 200
    here would tell an operator the crawl had finished when nothing has started.
    """
    return await ingestion_admin.create_run(
        session,
        subject_id=body.subject_id,
        source_ids=body.source_ids,
        stages=body.stages,
        dry_run=body.dry_run,
    )


@router.get("/ingestion/runs", response_model=RunListOut)
async def list_runs(
    session: SessionDep,
    _: CurrentAdmin,
    subject_id: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
) -> RunListOut:
    return RunListOut(runs=await ingestion_admin.list_runs(session, subject_id=subject_id, limit=limit))


@router.get("/ingestion/runs/{run_id}")
async def get_run(run_id: str, session: SessionDep, _: CurrentAdmin) -> dict[str, Any]:
    """One run with its full stage reports — the log an operator reads after a crawl."""
    return await ingestion_admin.get_run(session, run_id)


# ---------------------------------------------------------------------------
# Ingestion: candidates and review
# ---------------------------------------------------------------------------


@router.get("/ingestion/candidates", response_model=CandidateListOut)
async def list_candidates(
    session: SessionDep,
    _: CurrentAdmin,
    subject_id: str | None = Query(default=None),
    status_filter: str | None = Query(
        default="draft",
        alias="status",
        pattern="^(draft|in_review|approved|published|deprecated)$",
        description="Defaults to the review queue. Pass an empty value for every status.",
    ),
    target: str | None = Query(default=None, pattern="^(concept|curriculum|practice|project|assessment)$"),
    limit: int = Query(100, ge=1, le=500),
) -> CandidateListOut:
    """The review queue, lowest confidence first.

    Defaults to ``draft`` because the queue exists to be emptied, and a default of
    "everything" buries the twelve candidates needing a decision under nine hundred
    already-published ones.
    """
    return CandidateListOut(
        candidates=await ingestion_admin.list_candidates(
            session,
            subject_id=subject_id,
            status=status_filter or None,
            target=target,
            limit=limit,
        )
    )


@router.post("/ingestion/candidates/{candidate_id}/review")
async def review_candidate(
    candidate_id: str,
    body: CandidateReviewIn,
    session: SessionDep,
    admin: CurrentAdmin,
) -> dict[str, Any]:
    """Approve, reject or send back one candidate.

    Approving does **not** publish. It marks the candidate promotable and stops;
    writing it into the package directory and bumping the version is the build
    step. Review that mutates live content in place is review nobody can undo, and
    a learner mid-project would have the ground move under them.
    """
    return await ingestion_admin.review_candidate(
        session,
        candidate_id,
        decision=body.decision,
        notes=body.notes,
        payload=body.payload,
        reviewer=admin.email,
    )


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@router.get("/provenance/{entity_id}", response_model=ProvenanceTrailOut)
async def provenance(entity_id: str, session: SessionDep, _: CurrentAdmin) -> ProvenanceTrailOut:
    """"Where did this statement come from" for one published id.

    Part of the MVP surface even though the extractor behind it is a stub, because
    the tables it walks have to be designed for this question from the start. A
    provenance trail retrofitted after a package has already been published cannot
    be reconstructed — the chunks it would have cited are gone.

    Hand-authored content 404s here, and that is the correct answer: it has no
    ingestion trail, and inventing an empty one would make the endpoint useless as
    a way of telling generated content from written content.
    """
    return await ingestion_admin.provenance_trail(session, entity_id)
