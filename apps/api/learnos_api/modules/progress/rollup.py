"""Rolling evidence up into the progress payloads.

Two caches sit in front of this, and both are caches in the strict sense (either
can be thrown away without losing information):

* ``user_skill_state`` (Postgres) holds the last computed overall/coverage/
  dimensions for a skill. It is *also* the authoritative home of two values that
  are **not** derivable from evidence: the Elo-ish ``ability`` and
  ``consecutive_failures``, which are running state, not observations.
* ``progress:{user}:{subject}`` (Redis, 5 minute TTL) holds the assembled
  ``SubjectProgressOut``.

The short Redis TTL is deliberate. Evidence decays with time, so a rollup goes
subtly stale even with no writes; five minutes bounds that drift without making
the progress page recompute on every keystroke. Writes invalidate explicitly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Sequence

import sqlalchemy as sa
from learnos_schema import (
    DEFAULT_DIMENSION_WEIGHTS,
    AT_RISK_THRESHOLD,
    MASTERY_THRESHOLD,
    SkillMastery,
    SubjectPackage,
    compute_skill_mastery,
    update_ability,
)
from learnos_schema.mastery import Evidence
from sqlalchemy.ext.asyncio import AsyncSession

from ... import cache
from ...models import (
    EVENT_CONCEPT_VIEWED,
    EVENT_PRACTICE_PASSED,
    EVENT_PROJECT_COMPLETED,
    ProgressEvent,
    UserSkillState,
)
from ...schemas.progress import (
    DimensionOut,
    ProgressSummaryOut,
    SkillProgressOut,
    SubjectProgressOut,
)
from ..subjects.assemble import enum_value
from . import evidence as evidence_mod

#: The default ability of a learner with no history. Matches the column default.
INITIAL_ABILITY = 3.0

DIMENSION_ORDER = [enum_value(d) for d in DEFAULT_DIMENSION_WEIGHTS]


# ---------------------------------------------------------------------------
# Pure maths (no I/O): this is what the tests exercise
# ---------------------------------------------------------------------------


def masteries_from_evidence(
    package: SubjectPackage,
    evidence_by_skill: dict[str, list[Evidence]],
    *,
    now: datetime | None = None,
) -> dict[str, SkillMastery]:
    """One ``SkillMastery`` per skill in the package, measured or not.

    Every skill appears even with no evidence, because "untouched" is information
    the progress page has to render and an absent key would look like a bug.
    """
    return {
        skill.id: compute_skill_mastery(
            skill.id,
            evidence_by_skill.get(skill.id, []),
            package.weights_for_skill(skill.id),
            now,
        )
        for skill in package.curriculum.skills
    }


def dimensions_out(mastery: SkillMastery) -> dict[str, DimensionOut]:
    return {
        enum_value(dimension): DimensionOut(score=score.score, measured=score.measured)
        for dimension, score in mastery.dimensions.items()
    }


def aggregate_dimensions(masteries: Iterable[SkillMastery]) -> dict[str, DimensionOut]:
    """Subject-level per-dimension score: the mean over skills that measured it.

    Unmeasured skills are left out of the denominator rather than counted as zero,
    for the same reason unmeasured dimensions are left out of a skill's overall: a
    learner who has done no labs has an unknown lab score, not a zero one.
    """
    totals: dict[str, list[float]] = defaultdict(list)
    for mastery in masteries:
        for dimension, score in mastery.dimensions.items():
            if score.measured:
                totals[enum_value(dimension)].append(score.score)
    out: dict[str, DimensionOut] = {}
    for dimension in DIMENSION_ORDER:
        scores = totals.get(dimension, [])
        out[dimension] = DimensionOut(
            score=sum(scores) / len(scores) if scores else 0.0,
            measured=bool(scores),
        )
    return out


def overall_from_masteries(masteries: Iterable[SkillMastery]) -> tuple[float, float]:
    """Subject overall and coverage, averaged over skills with any evidence.

    Skills that have never been touched are excluded, so starting a new subject
    does not show 3% overall: it shows the score on what has actually been done,
    with ``skills_total`` alongside it to give the honest denominator.
    """
    measured = [m for m in masteries if m.evidence_count > 0]
    if not measured:
        return 0.0, 0.0
    overall = sum(m.overall for m in measured) / len(measured)
    coverage = sum(m.coverage for m in measured) / len(measured)
    return overall, coverage


def streak_days(days_active: Sequence[date], today: date) -> int:
    """Consecutive days with activity, counting back from today or yesterday.

    Yesterday counts as the anchor so that a learner who has not practised yet
    today does not watch their streak read zero all morning.
    """
    active = set(days_active)
    if not active:
        return 0
    anchor = today if today in active else today - timedelta(days=1)
    if anchor not in active:
        return 0
    count = 0
    cursor = anchor
    while cursor in active:
        count += 1
        cursor -= timedelta(days=1)
    return count


# ---------------------------------------------------------------------------
# Persistence of the derived state
# ---------------------------------------------------------------------------


async def load_skill_states(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    skill_ids: Sequence[str] | None = None,
) -> dict[str, UserSkillState]:
    stmt = sa.select(UserSkillState).where(
        UserSkillState.user_id == user_id,
        UserSkillState.subject_id == subject_id,
    )
    if skill_ids is not None:
        if not skill_ids:
            return {}
        stmt = stmt.where(UserSkillState.skill_id.in_(list(skill_ids)))
    result = await session.execute(stmt)
    return {row.skill_id: row for row in result.scalars()}


async def get_or_create_state(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    skill_id: str,
) -> UserSkillState:
    existing = await session.execute(
        sa.select(UserSkillState).where(
            UserSkillState.user_id == user_id,
            UserSkillState.subject_id == subject_id,
            UserSkillState.skill_id == skill_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row
    row = UserSkillState(
        user_id=user_id,
        subject_id=subject_id,
        skill_id=skill_id,
        ability=INITIAL_ABILITY,
    )
    session.add(row)
    await session.flush()
    return row


async def sync_skill_states(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    masteries: dict[str, SkillMastery],
) -> dict[str, UserSkillState]:
    """Write the derived numbers back onto ``user_skill_state``.

    ``ability`` and ``consecutive_failures`` are untouched here: they are updated
    by ``apply_attempt_outcome`` on submission and would be destroyed by a rollup.
    """
    states = await load_skill_states(session, user_id=user_id, subject_id=subject_id, skill_ids=list(masteries))
    for skill_id, mastery in masteries.items():
        state = states.get(skill_id)
        if state is None:
            state = UserSkillState(
                user_id=user_id,
                subject_id=subject_id,
                skill_id=skill_id,
                ability=INITIAL_ABILITY,
            )
            session.add(state)
            states[skill_id] = state
        state.overall = mastery.overall
        state.coverage = mastery.coverage
        state.dimensions = {
            enum_value(dimension): {
                "score": score.score,
                "measured": score.measured,
                "evidence_count": score.evidence_count,
            }
            for dimension, score in mastery.dimensions.items()
        }
        state.evidence_count = mastery.evidence_count
        state.state = mastery.state
        if mastery.last_practiced_at is not None:
            state.last_practiced_at = mastery.last_practiced_at
    await session.flush()
    return states


async def apply_attempt_outcome(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    skill_ids: Iterable[str],
    difficulty: int,
    score: float,
    passed: bool,
    at: datetime,
) -> dict[str, UserSkillState]:
    """Update the running per-skill state a submission changes.

    ``consecutive_failures`` is what makes the recommender back off: two failures
    in a row means the learner is missing something upstream, not that they need a
    third go at the same difficulty.
    """
    touched: dict[str, UserSkillState] = {}
    for skill_id in skill_ids:
        state = await get_or_create_state(session, user_id=user_id, subject_id=subject_id, skill_id=skill_id)
        state.ability = update_ability(state.ability, difficulty, score)
        state.consecutive_failures = 0 if passed else state.consecutive_failures + 1
        state.last_practiced_at = at
        touched[skill_id] = state
    await session.flush()
    return touched


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


async def compute_progress(
    session: AsyncSession,
    *,
    user_id,
    package: SubjectPackage,
    now: datetime | None = None,
) -> SubjectProgressOut:
    """Recompute a subject's progress from evidence. No cache involved."""
    now = now or datetime.now(timezone.utc)
    subject_id = package.id
    evidence_by_skill = await evidence_mod.load_evidence(session, user_id=user_id, subject_id=subject_id)
    masteries = masteries_from_evidence(package, evidence_by_skill, now=now)
    states = await sync_skill_states(session, user_id=user_id, subject_id=subject_id, masteries=masteries)
    activity = await _activity(session, user_id=user_id, subject_id=subject_id, now=now)

    overall, coverage = overall_from_masteries(masteries.values())
    skills = [
        SkillProgressOut(
            skill_id=skill.id,
            title=skill.title,
            overall=masteries[skill.id].overall,
            coverage=masteries[skill.id].coverage,
            state=masteries[skill.id].state,  # type: ignore[arg-type]
            ability=states[skill.id].ability if skill.id in states else INITIAL_ABILITY,
            dimensions=dimensions_out(masteries[skill.id]),  # type: ignore[arg-type]
            last_practiced_at=masteries[skill.id].last_practiced_at,
        )
        for skill in package.curriculum.skills
    ]

    summary = ProgressSummaryOut(
        overall=overall,
        coverage=coverage,
        skills_total=len(masteries),
        skills_mastered=sum(1 for m in masteries.values() if m.overall >= MASTERY_THRESHOLD and m.evidence_count > 0),
        skills_at_risk=sum(1 for m in masteries.values() if m.evidence_count > 0 and m.overall < AT_RISK_THRESHOLD),
        concepts_seen=int(activity["concepts_seen"]),
        practice_passed=int(activity["practice_passed"]),
        projects_completed=int(activity["projects_completed"]),
        minutes_practised=activity["minutes"],
        streak_days=int(activity["streak_days"]),
    )

    return SubjectProgressOut(
        subject_id=subject_id,
        summary=summary,
        dimensions=aggregate_dimensions(masteries.values()),  # type: ignore[arg-type]
        skills=skills,
    )


async def get_progress(
    session: AsyncSession,
    *,
    user_id,
    package: SubjectPackage,
    use_cache: bool = True,
) -> SubjectProgressOut:
    key = cache.progress_key(str(user_id), package.id)
    if use_cache:
        cached = await cache.get_json(key)
        if cached is not None:
            return SubjectProgressOut.model_validate(cached)
    progress = await compute_progress(session, user_id=user_id, package=package)
    await cache.set_json(key, progress.model_dump(mode="json"), cache.TTL_PROGRESS)
    return progress


async def invalidate(user_id, subject_id: str) -> None:
    await cache.delete(cache.progress_key(str(user_id), subject_id))


async def catalog_snapshot(session: AsyncSession, *, user_id) -> dict[str, tuple[float, int]]:
    """``subject_id -> (overall, skills_mastered)`` for every subject at once.

    The one place in the service that reads ``user_skill_state`` as a cache instead
    of recomputing from evidence. The catalogue lists every subject, and a full
    rollup per card would make the landing page the most expensive request in the
    product to render three numbers per tile. The cost of the shortcut is that a
    card can lag a rollup by one write; the progress page, where the number is
    load-bearing, always recomputes.

    Averaged over skills with evidence, matching :func:`overall_from_masteries`,
    so a freshly started subject reads as its score-so-far rather than as 3%.
    """
    result = await session.execute(
        sa.select(
            UserSkillState.subject_id,
            sa.func.avg(UserSkillState.overall),
            sa.func.sum(sa.case((UserSkillState.overall >= MASTERY_THRESHOLD, 1), else_=0)),
        )
        .where(UserSkillState.user_id == user_id, UserSkillState.evidence_count > 0)
        .group_by(UserSkillState.subject_id)
    )
    return {
        str(subject_id): (float(average or 0.0), int(mastered or 0))
        for subject_id, average, mastered in result.all()
    }


async def mastery_lookup(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    package: SubjectPackage,
) -> dict[str, SkillMastery]:
    """``skill_id -> SkillMastery`` for the graph, readiness and recommender.

    Recomputed from evidence rather than read from ``user_skill_state`` so that a
    readiness decision is never made on a rollup that a failed write left behind.
    """
    evidence_by_skill = await evidence_mod.load_evidence(session, user_id=user_id, subject_id=subject_id)
    return masteries_from_evidence(package, evidence_by_skill)


async def history(
    session: AsyncSession,
    *,
    user_id,
    package: SubjectPackage,
    days: int = 30,
) -> list[tuple[str, float, int, dict[str, DimensionOut]]]:
    """Replay evidence day by day to get an honest history curve.

    No historical snapshot table: the evidence rows *are* the history, and
    recomputing at each cutoff means the curve reflects today's maths rather than
    whatever the maths was on the day the row was written.

    Each point carries the per-dimension breakdown as well as the overall, because
    the interesting question is usually which axis moved. Retention decaying while
    concept holds steady is a different story from both sliding together, and one
    number a day cannot tell them apart. The dimensions come from the same
    :func:`aggregate_dimensions` the live rollup uses, so a point in the curve and
    today's dashboard cannot disagree.
    """
    days = min(max(days, 1), 365)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days - 1)
    evidence_by_skill = await evidence_mod.load_evidence(session, user_id=user_id, subject_id=package.id)

    points: list[tuple[str, float, int, dict[str, DimensionOut]]] = []
    for offset in range(days):
        cutoff_day = (start + timedelta(days=offset)).date()
        cutoff = datetime.combine(cutoff_day, datetime.max.time()).replace(tzinfo=timezone.utc)
        truncated = {
            skill_id: [e for e in items if e.created_at <= cutoff] for skill_id, items in evidence_by_skill.items()
        }
        masteries = masteries_from_evidence(package, truncated, now=cutoff)
        overall, _ = overall_from_masteries(masteries.values())
        mastered = sum(1 for m in masteries.values() if m.evidence_count > 0 and m.overall >= MASTERY_THRESHOLD)
        points.append((cutoff_day.isoformat(), overall, mastered, aggregate_dimensions(masteries.values())))
    return points


async def _activity(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    now: datetime,
) -> dict[str, float]:
    """Counts derived from ``progress_events``.

    Distinct entity ids, not row counts: viewing the same concept twice is one
    concept seen, and passing the same task twice is one task passed.
    """
    distinct_stmt = (
        sa.select(
            ProgressEvent.kind,
            sa.func.count(sa.distinct(ProgressEvent.entity_id)),
        )
        .where(
            ProgressEvent.user_id == user_id,
            ProgressEvent.subject_id == subject_id,
            ProgressEvent.kind.in_([EVENT_CONCEPT_VIEWED, EVENT_PRACTICE_PASSED, EVENT_PROJECT_COMPLETED]),
        )
        .group_by(ProgressEvent.kind)
    )
    counts = {kind: count for kind, count in (await session.execute(distinct_stmt)).all()}

    minutes = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(ProgressEvent.minutes), 0.0)).where(
            ProgressEvent.user_id == user_id,
            ProgressEvent.subject_id == subject_id,
        )
    )

    # Streak is computed in Python from raw timestamps because date truncation
    # syntax differs between Postgres and the SQLite used by the test suite, and a
    # streak over a year of activity is a few hundred rows.
    since = now - timedelta(days=400)
    day_rows = await session.execute(
        sa.select(ProgressEvent.occurred_at).where(
            ProgressEvent.user_id == user_id,
            ProgressEvent.subject_id == subject_id,
            ProgressEvent.occurred_at >= since,
        )
    )
    active_days = []
    for (occurred_at,) in day_rows.all():
        stamp = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=timezone.utc)
        active_days.append(stamp.astimezone(timezone.utc).date())

    return {
        "concepts_seen": float(counts.get(EVENT_CONCEPT_VIEWED, 0)),
        "practice_passed": float(counts.get(EVENT_PRACTICE_PASSED, 0)),
        "projects_completed": float(counts.get(EVENT_PROJECT_COMPLETED, 0)),
        "minutes": float(minutes or 0.0),
        "streak_days": float(streak_days(active_days, now.astimezone(timezone.utc).date())),
    }
