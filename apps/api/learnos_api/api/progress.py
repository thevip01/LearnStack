"""Progress routes.

All three require authentication — there is no anonymous progress to report — and
all three recompute from evidence rather than reading ``user_skill_state``. That
is the expensive choice on purpose: this is the page a learner uses to decide
what to trust about their own ability, and a number served from a stale rollup is
worse than a slower page.

The one place ``measured`` must survive intact is here. An unmeasured dimension
travels as ``{"score": 0.0, "measured": false}`` and the UI renders a dash; the
route must never collapse that into a zero to make the JSON tidier.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..modules import knowledge, practice
from ..modules.auth.deps import CurrentUser
from ..modules.progress import evidence as evidence_mod
from ..modules.progress import rollup
from ..modules.subjects import assemble
from ..schemas.practice import PracticeSummary
from ..schemas.progress import EvidenceOut, HistoryOut, HistoryPointOut, SkillDetailOut, SubjectProgressOut
from .deps import RegistryDep, SessionDep, resolve_subject

router = APIRouter(prefix="/progress", tags=["progress"])

#: How many practice tasks the skill drawer suggests. Enough to choose from,
#: few enough that the drawer is not a second practice queue.
RECOMMENDED_PRACTICE_LIMIT = 4


@router.get("/{subject_id}", response_model=SubjectProgressOut)
async def subject_progress(
    subject_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: CurrentUser,
    refresh: bool = Query(False, description="Bypass the 5 minute rollup cache."),
) -> SubjectProgressOut:
    subject = resolve_subject(registry, subject_id)
    return await rollup.get_progress(
        session, user_id=user.id, package=subject.package, use_cache=not refresh
    )


@router.get("/{subject_id}/skills/{skill_id}", response_model=SkillDetailOut)
async def skill_detail(
    subject_id: str,
    skill_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: CurrentUser,
) -> SkillDetailOut:
    """Everything behind one number: the evidence, the gate, and what to do next.

    This is the endpoint that makes the mastery model defensible. A learner who
    disagrees with a score can read the rows it was computed from, including how
    much each has decayed, which is only possible because evidence is append-only.
    """
    subject = resolve_subject(registry, subject_id)
    skill = registry.skill(subject_id, skill_id)
    package = subject.package

    progress = await rollup.get_progress(session, user_id=user.id, package=package, use_cache=False)
    mastery = next((item for item in progress.skills if item.skill_id == skill_id), None)
    if mastery is None:  # pragma: no cover - registry.skill already 404s
        raise AssertionError(f"skill {skill_id!r} is in the package but missing from the rollup")

    rows = await evidence_mod.evidence_rows_for_skill(
        session, user_id=user.id, subject_id=subject_id, skill_id=skill_id
    )
    masteries = await rollup.mastery_lookup(
        session, user_id=user.id, subject_id=subject_id, package=package
    )
    stats = await practice.attempt_stats(session, user_id=user.id, subject_id=subject_id)

    # Unpassed tasks first, easiest first. A drawer that leads with work already
    # done is a drawer nobody clicks twice.
    candidates = sorted(
        (task for task in package.practice.values() if skill_id in task.skills),
        key=lambda task: (stats.get(task.id, ("untouched", None, 0))[0] == "passed", task.difficulty, task.id),
    )
    recommended: list[PracticeSummary] = []
    for task in candidates[:RECOMMENDED_PRACTICE_LIMIT]:
        state, best, count = stats.get(task.id, ("untouched", None, 0))
        recommended.append(assemble.practice_summary(task, state=state, best_score=best, attempts=count))

    return SkillDetailOut(
        skill=skill.model_dump(mode="json"),
        mastery=mastery,
        evidence=[_evidence_out(row) for row in rows],
        readiness=knowledge.readiness_for_skill(package, skill_id, masteries),
        recommended_practice=recommended,
    )


def _evidence_out(row) -> EvidenceOut:
    """One stored observation, with its decay recomputed on read.

    ``recency_factor`` is a method on the schema model rather than a stored column
    precisely so that it is always current: a row written 40 days ago should be
    visibly worth less today than it was yesterday, and a persisted value would be
    a lie the moment it was written.
    """
    schema_row = evidence_mod.to_schema(row)
    return EvidenceOut(
        dimension=row.dimension,
        score=row.score,
        weight=row.weight,
        source_type=row.source_type,
        source_id=row.source_id,
        hints_used=row.hints_used,
        created_at=schema_row.created_at,
        recency_factor=schema_row.recency_factor(),
    )


@router.get("/{subject_id}/history", response_model=HistoryOut)
async def history(
    subject_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
) -> HistoryOut:
    """The mastery curve, replayed from evidence.

    There is no snapshot table. Each point is the rollup recomputed with a cutoff,
    so the curve reflects today's maths rather than whatever the maths was on the
    day each row was written — and a change to the decay constant redraws history
    instead of leaving a discontinuity in it.
    """
    subject = resolve_subject(registry, subject_id)
    points = await rollup.history(session, user_id=user.id, package=subject.package, days=days)
    return HistoryOut(
        points=[
            HistoryPointOut(date=date, overall=overall, skills_mastered=mastered)
            for date, overall, mastered in points
        ]
    )
