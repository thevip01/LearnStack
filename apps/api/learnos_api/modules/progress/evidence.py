"""Evidence: the only thing this system actually stores about a learner.

``mastery_evidence`` is append-only. Nothing updates a row, nothing deletes one,
and no score is ever written to it — a score is a *derived* value computed from
the rows by ``learnos_schema.mastery``. That choice costs a little query time and
buys three things:

* Any rollup can be recomputed from scratch after a maths change, so tuning the
  hint penalty does not require a data migration.
* "Why is my mastery 62%?" is answerable by listing rows.
* Recency decay works, because the timestamp of each observation survives.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

import sqlalchemy as sa
from learnos_schema import Evidence, PracticeTask
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import MasteryEvidence
from ..subjects.assemble import enum_value

#: A difficulty-1 task is weak evidence and a difficulty-10 task is strong
#: evidence, but the spread is deliberately narrow. Passing ten easy tasks should
#: not out-weigh passing one hard one, and one hard task should not be enough on
#: its own either.
WEIGHT_AT_MIN_DIFFICULTY = 0.6
WEIGHT_AT_MAX_DIFFICULTY = 1.6


def difficulty_weight(difficulty: int) -> float:
    """Linear map from the 1-10 difficulty scale onto an evidence weight."""
    clamped = min(max(int(difficulty), 1), 10)
    span = WEIGHT_AT_MAX_DIFFICULTY - WEIGHT_AT_MIN_DIFFICULTY
    return WEIGHT_AT_MIN_DIFFICULTY + span * (clamped - 1) / 9.0


def evidence_for_task(
    task: PracticeTask,
    *,
    score: float,
    hints_used: int,
    source_type: str = "practice",
) -> list[Evidence]:
    """One evidence row per skill the task claims to exercise.

    The task's ``evaluation.dimension`` decides which axis is being measured, which
    is what makes a debug task fill the debugging dimension and a quiz fill the
    concept one. A task with no ``skills`` produces no evidence at all: it can
    still be graded and shown, it simply moves no needle, and that is a content
    bug the package validator warns about rather than something to paper over here.
    """
    dimension = enum_value(task.evaluation.dimension)
    weight = difficulty_weight(task.difficulty)
    return [
        Evidence(
            skill_id=skill_id,
            dimension=dimension,  # type: ignore[arg-type]
            score=min(max(score, 0.0), 1.0),
            weight=weight,
            source_type=source_type,
            source_id=task.id,
            hints_used=hints_used,
        )
        for skill_id in task.skills
    ]


def persist_evidence(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    evidence: Iterable[Evidence],
) -> list[MasteryEvidence]:
    """Add rows to the session. The caller owns the transaction boundary."""
    rows: list[MasteryEvidence] = []
    for item in evidence:
        row = MasteryEvidence(
            user_id=user_id,
            subject_id=subject_id,
            skill_id=item.skill_id,
            dimension=enum_value(item.dimension),
            score=item.score,
            weight=item.weight,
            source_type=item.source_type,
            source_id=item.source_id,
            hints_used=item.hints_used,
            created_at=item.created_at,
        )
        session.add(row)
        rows.append(row)
    return rows


def to_schema(row: MasteryEvidence) -> Evidence:
    """ORM row -> schema model, so the maths only ever sees one shape.

    ``created_at`` is forced to aware UTC because a driver that hands back a naive
    datetime would otherwise make ``recency_factor`` compare naive to aware and
    raise, and the recency maths is not the place to discover a driver quirk.
    """
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return Evidence(
        skill_id=row.skill_id,
        dimension=row.dimension,  # type: ignore[arg-type]
        score=row.score,
        weight=row.weight,
        source_type=row.source_type,
        source_id=row.source_id,
        hints_used=row.hints_used,
        created_at=created,
    )


async def load_evidence(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    skill_ids: Sequence[str] | None = None,
    since: datetime | None = None,
) -> dict[str, list[Evidence]]:
    """Every evidence row for one learner in one subject, grouped by skill.

    One query for the whole subject rather than one per skill: a rollup touches
    every skill anyway, and the row count per learner per subject is in the
    hundreds, not the millions.
    """
    stmt = sa.select(MasteryEvidence).where(
        MasteryEvidence.user_id == user_id,
        MasteryEvidence.subject_id == subject_id,
    )
    if skill_ids is not None:
        if not skill_ids:
            return {}
        stmt = stmt.where(MasteryEvidence.skill_id.in_(list(skill_ids)))
    if since is not None:
        stmt = stmt.where(MasteryEvidence.created_at >= since)
    stmt = stmt.order_by(MasteryEvidence.created_at)

    result = await session.execute(stmt)
    grouped: dict[str, list[Evidence]] = {}
    for row in result.scalars():
        grouped.setdefault(row.skill_id, []).append(to_schema(row))
    return grouped


async def evidence_rows_for_skill(
    session: AsyncSession,
    *,
    user_id,
    subject_id: str,
    skill_id: str,
    limit: int = 100,
) -> list[MasteryEvidence]:
    """Newest-first evidence for the skill detail drawer."""
    stmt = (
        sa.select(MasteryEvidence)
        .where(
            MasteryEvidence.user_id == user_id,
            MasteryEvidence.subject_id == subject_id,
            MasteryEvidence.skill_id == skill_id,
        )
        .order_by(MasteryEvidence.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())
