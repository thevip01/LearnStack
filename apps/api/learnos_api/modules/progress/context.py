"""Assembling the recommender's view of a learner.

Split out from ``recommender`` so that the ranking rules stay pure and testable
over fixtures, and from ``rollup`` so that the progress payload does not pay for
the extra queries a recommendation needs.

The queries are deliberately coarse (one per signal, whole-subject) because the
recommender considers every skill anyway and the alternative is a per-skill fan-out
on a request that already runs the mastery rollup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

import sqlalchemy as sa
from learnos_schema import SubjectPackage
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import EVENT_CONCEPT_VIEWED, Attempt, ProgressEvent, UserSkillState
from .recommender import LearnerView
from .rollup import mastery_lookup


async def passed_task_ids(session: AsyncSession, *, user_id: uuid.UUID, subject_id: str) -> set[str]:
    result = await session.execute(
        sa.select(Attempt.task_id).where(
            Attempt.user_id == user_id,
            Attempt.subject_id == subject_id,
            Attempt.state == "passed",
        )
    )
    return {str(task_id) for task_id in result.scalars()}


async def viewed_concept_ids(session: AsyncSession, *, user_id: uuid.UUID, subject_id: str) -> set[str]:
    """Concepts the learner has opened.

    Read from the activity log rather than from a "completed" flag, because there is
    no honest way for a learner to mark a lesson understood and pretending otherwise
    would make the recommender confident about something it cannot know. Opening a
    lesson is weak evidence, and it is only used to avoid suggesting the same page
    twice.
    """
    result = await session.execute(
        sa.select(ProgressEvent.entity_id).where(
            ProgressEvent.user_id == user_id,
            ProgressEvent.subject_id == subject_id,
            ProgressEvent.kind == EVENT_CONCEPT_VIEWED,
            ProgressEvent.entity_id.is_not(None),
        )
    )
    return {str(entity_id) for entity_id in result.scalars() if entity_id}


async def adaptive_state(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: str,
) -> tuple[dict[str, float], dict[str, int], dict[str, datetime | None]]:
    result = await session.execute(
        sa.select(
            UserSkillState.skill_id,
            UserSkillState.ability,
            UserSkillState.consecutive_failures,
            UserSkillState.last_practiced_at,
        ).where(UserSkillState.user_id == user_id, UserSkillState.subject_id == subject_id)
    )
    ability: dict[str, float] = {}
    failures: dict[str, int] = {}
    practised: dict[str, datetime | None] = {}
    for skill_id, value, failure_count, last in result.all():
        ability[str(skill_id)] = float(value)
        failures[str(skill_id)] = int(failure_count or 0)
        practised[str(skill_id)] = last
    return ability, failures, practised


async def learner_view(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    package: SubjectPackage,
) -> LearnerView:
    """Everything the recommender needs, in one place.

    An anonymous caller gets ``LearnerView.empty()``, which produces the
    curriculum-order recommendation a first-time visitor should see rather than an
    error or an empty list.
    """
    if user_id is None:
        return LearnerView.empty()

    subject_id = package.manifest.id
    masteries = await mastery_lookup(session, user_id=user_id, subject_id=subject_id, package=package)
    ability, failures, practised = await adaptive_state(session, user_id=user_id, subject_id=subject_id)
    passed = await passed_task_ids(session, user_id=user_id, subject_id=subject_id)
    viewed = await viewed_concept_ids(session, user_id=user_id, subject_id=subject_id)

    return LearnerView(
        masteries=masteries,
        ability=ability,
        consecutive_failures=failures,
        last_practiced=practised,
        passed_task_ids=frozenset(passed),
        viewed_concept_ids=frozenset(viewed),
    )


async def log_concept_view(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: str,
    concept_id: str,
    minutes: float = 0.0,
    at: datetime | None = None,
) -> ProgressEvent:
    """Record that a lesson was opened.

    Called from the concept route. Deliberately not deduplicated: re-reading a
    lesson is a signal worth keeping, and the recommender only asks whether the set
    is non-empty.
    """
    event = ProgressEvent(
        user_id=user_id,
        subject_id=subject_id,
        kind=EVENT_CONCEPT_VIEWED,
        entity_id=concept_id,
        payload={},
        minutes=max(float(minutes), 0.0),
        occurred_at=at or datetime.now(timezone.utc),
    )
    session.add(event)
    return event


async def recent_events(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: str | None = None,
    kinds: Sequence[str] | None = None,
    limit: int = 50,
) -> list[ProgressEvent]:
    stmt = sa.select(ProgressEvent).where(ProgressEvent.user_id == user_id)
    if subject_id:
        stmt = stmt.where(ProgressEvent.subject_id == subject_id)
    if kinds:
        stmt = stmt.where(ProgressEvent.kind.in_(list(kinds)))
    stmt = stmt.order_by(ProgressEvent.occurred_at.desc()).limit(min(max(limit, 1), 200))
    result = await session.execute(stmt)
    return list(result.scalars())
