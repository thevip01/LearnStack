"""Attempt and hint lifecycle.

An attempt is the learner's open session on one task; a submission is one graded
push against it. This module owns the transitions between those and nothing else —
grading lives in the per-kind modules, evidence lives in ``progress``.

Two decisions worth naming:

* **One open attempt per (user, task).** Opening a task twice returns the same
  attempt rather than minting a second one, so hint usage and elapsed time cannot
  be reset by reloading the page. A learner who wants a genuinely clean run gets
  it after passing or after ``reset``.
* **A hint is a write.** ``GET``-shaped "just show me the hint" would let the UI
  prefetch hints and silently spend the learner's discount. The contract makes it
  a ``POST`` and this module records it before returning the text.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import sqlalchemy as sa
from learnos_schema import Hint, PracticeTask
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import Conflict, NotFound
from ...models import Attempt, HintReveal, Submission
from ...schemas.practice import AttemptOut, HintOut, PracticeState
from .results import GradeOutcome


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Force aware UTC. SQLite hands back naive datetimes even for timezone=True."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def time_limit_for(task: PracticeTask) -> int | None:
    return getattr(task, "time_limit_s", None)


# ---------------------------------------------------------------------------
# Attempt lookup and creation
# ---------------------------------------------------------------------------


async def open_attempt(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: str,
    task: PracticeTask,
) -> Attempt:
    """Return the learner's working attempt on this task, creating one if needed.

    An attempt is a *working session*, not a single push: it stays open across
    failed submissions and closes only on a pass. That is what makes the hint
    ledger tamper-proof. If a failed submission ended the attempt, a learner could
    take the solution-revealing hint, submit anything, and open a clean attempt
    with ``hints_used`` back at zero — collecting full-weight evidence for work the
    platform had already handed them.

    A learner who has already passed gets a *new* attempt, because re-doing solved
    work is retention evidence and it should be measured unhinted and from scratch.
    """
    existing = await session.scalar(
        sa.select(Attempt)
        .where(
            Attempt.user_id == user_id,
            Attempt.task_id == task.id,
            Attempt.state != "passed",
        )
        .order_by(Attempt.started_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    attempt = Attempt(
        user_id=user_id,
        task_id=task.id,
        subject_id=subject_id,
        started_at=now(),
        state="in_progress",
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def load_attempt(
    session: AsyncSession,
    attempt_id: str | uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> Attempt:
    """Load an attempt the caller owns, or raise.

    Ownership is enforced in the query rather than checked afterwards, so a
    mistyped route cannot leak another learner's attempt by forgetting a guard.
    """
    try:
        parsed = attempt_id if isinstance(attempt_id, uuid.UUID) else uuid.UUID(str(attempt_id))
    except (ValueError, AttributeError, TypeError):
        raise NotFound("attempt not found", {"reason": "attempt_not_found"}) from None

    attempt = await session.scalar(
        sa.select(Attempt).where(Attempt.id == parsed, Attempt.user_id == user_id)
    )
    if attempt is None:
        raise NotFound("attempt not found", {"reason": "attempt_not_found"})
    return attempt


async def latest_attempts(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: str,
) -> dict[str, Attempt]:
    """``task_id -> most recent attempt`` for one subject.

    Used to decorate practice summaries. One query for the whole subject: the
    practice list renders every task at once, so N+1 here would be N+1 on the
    hottest read in the product.
    """
    result = await session.execute(
        sa.select(Attempt)
        .where(Attempt.user_id == user_id, Attempt.subject_id == subject_id)
        .order_by(Attempt.started_at)
    )
    latest: dict[str, Attempt] = {}
    for attempt in result.scalars():
        latest[attempt.task_id] = attempt
    return latest


async def attempt_stats(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: str,
) -> dict[str, tuple[PracticeState, float | None, int]]:
    """``task_id -> (state, best_score, attempt_count)``.

    ``state`` is the *best* outcome across attempts, not the latest: a learner who
    passed a task and then reopened it to experiment has still passed it, and
    showing the task as in-progress would make the progress view lie.
    """
    result = await session.execute(
        sa.select(
            Attempt.task_id,
            sa.func.count(Attempt.id),
            sa.func.max(Attempt.best_score),
            sa.func.sum(sa.case((Attempt.state == "passed", 1), else_=0)),
            sa.func.sum(sa.case((Attempt.state == "in_progress", 1), else_=0)),
        )
        .where(Attempt.user_id == user_id, Attempt.subject_id == subject_id)
        .group_by(Attempt.task_id)
    )
    stats: dict[str, tuple[PracticeState, float | None, int]] = {}
    for task_id, count, best, passed_count, open_count in result.all():
        if passed_count:
            state: PracticeState = "passed"
        elif open_count:
            state = "in_progress"
        elif count:
            state = "failed"
        else:  # pragma: no cover - group by guarantees count >= 1
            state = "untouched"
        stats[str(task_id)] = (state, float(best) if best is not None else None, int(count or 0))
    return stats


def attempt_out(attempt: Attempt, task: PracticeTask) -> AttemptOut:
    started = _aware(attempt.started_at) or now()
    return AttemptOut(
        attempt_id=str(attempt.id),
        task_id=attempt.task_id,
        started_at=started,
        hints_used=int(attempt.hints_used or 0),
        submission_count=int(attempt.submission_count or 0),
        time_limit_s=time_limit_for(task),
    )


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------


def hint_ladder(task: PracticeTask) -> list[Hint]:
    return sorted(task.hints, key=lambda hint: hint.level)


async def revealed_levels(session: AsyncSession, attempt_id: uuid.UUID) -> set[int]:
    result = await session.execute(sa.select(HintReveal.level).where(HintReveal.attempt_id == attempt_id))
    return {int(level) for level in result.scalars()}


async def reveal_hint(
    session: AsyncSession,
    *,
    attempt: Attempt,
    task: PracticeTask,
    level: int | None = None,
) -> HintOut:
    """Reveal the next hint (or a specific level) and record that it was taken.

    Requesting a level out of order is allowed but reveals every level up to it,
    and is charged accordingly. Skipping straight to the giveaway is a legitimate
    choice; getting it at level-1 prices is not.
    """
    ladder = hint_ladder(task)
    if not ladder:
        raise NotFound("this task has no hints", {"reason": "no_hints"})

    already = await revealed_levels(session, attempt.id)
    if level is None:
        remaining = [hint for hint in ladder if hint.level not in already]
        if not remaining:
            raise Conflict(
                "every hint for this task has already been revealed",
                {"reason": "hints_exhausted", "hints_used": len(already)},
            )
        target = remaining[0]
    else:
        match = next((hint for hint in ladder if hint.level == level), None)
        if match is None:
            raise NotFound(
                f"this task has no hint at level {level}",
                {"reason": "no_such_hint", "levels": [hint.level for hint in ladder]},
            )
        target = match

    newly_charged = [hint for hint in ladder if hint.level <= target.level and hint.level not in already]
    stamp = now()
    for hint in newly_charged:
        session.add(HintReveal(attempt_id=attempt.id, level=hint.level, revealed_at=stamp))

    revealed_now = already | {hint.level for hint in newly_charged}
    attempt.hints_used = len(revealed_now)
    if any(hint.reveals_solution for hint in ladder if hint.level in revealed_now):
        attempt.solution_revealed = True
    await session.flush()

    return HintOut(
        level=target.level,
        md=target.md,
        hints_remaining=max(len(ladder) - len(revealed_now), 0),
        reveals_solution=bool(target.reveals_solution),
    )


async def revealed_hints(
    session: AsyncSession,
    *,
    attempt: Attempt,
    task: PracticeTask,
) -> list[HintOut]:
    """Hints already paid for on this attempt, so a reload does not lose them."""
    levels = await revealed_levels(session, attempt.id)
    ladder = hint_ladder(task)
    return [
        HintOut(
            level=hint.level,
            md=hint.md,
            hints_remaining=max(len(ladder) - len(levels), 0),
            reveals_solution=bool(hint.reveals_solution),
        )
        for hint in ladder
        if hint.level in levels
    ]


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def _serialisable(value: Any) -> Any:
    """Coerce a submission payload into something the JSON column accepts."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _serialisable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialisable(item) for item in value]
    return value


async def record_submission(
    session: AsyncSession,
    *,
    attempt: Attempt,
    dimension: str,
    payload: Any,
    outcome: GradeOutcome,
    duration_ms: int,
    execution_id: uuid.UUID | None = None,
) -> Submission:
    """Persist one graded push and advance the attempt.

    An attempt that has passed stays passed. Re-attempting a solved task is
    encouraged — it is how retention evidence gets collected — but a later weaker
    run must not downgrade the earlier result, or practice would become something
    a learner is afraid to revisit.
    """
    stamp = now()
    submission = Submission(
        attempt_id=attempt.id,
        payload=_serialisable(payload),
        score=float(outcome.score),
        passed=bool(outcome.passed),
        dimension=dimension,
        feedback_md=outcome.feedback_md,
        per_item_results=(
            [result.model_dump(mode="json") for result in outcome.question_results]
            if outcome.question_results
            else None
        ),
        graded_at=stamp,
        duration_ms=max(int(duration_ms), 0),
        execution_id=execution_id,
    )
    session.add(submission)

    attempt.submission_count = int(attempt.submission_count or 0) + 1
    attempt.submitted_at = stamp
    previous_best = attempt.best_score
    if previous_best is None or outcome.score > previous_best:
        attempt.best_score = float(outcome.score)
    if outcome.passed:
        attempt.state = "passed"
    elif attempt.state != "passed":
        attempt.state = "failed"

    await session.flush()
    return submission


async def submission_history(
    session: AsyncSession,
    *,
    attempt_id: uuid.UUID,
    limit: int = 20,
) -> list[Submission]:
    result = await session.execute(
        sa.select(Submission)
        .where(Submission.attempt_id == attempt_id)
        .order_by(Submission.graded_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def has_passed(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    task_ids: Sequence[str] | Iterable[str],
) -> set[str]:
    """Which of these tasks the learner has already passed.

    The recommender uses this to avoid handing back a task that is already green.
    """
    ids = [str(task_id) for task_id in task_ids]
    if not ids:
        return set()
    result = await session.execute(
        sa.select(Attempt.task_id).where(
            Attempt.user_id == user_id,
            Attempt.task_id.in_(ids),
            Attempt.state == "passed",
        )
    )
    return {str(task_id) for task_id in result.scalars()}


def elapsed_ms(attempt: Attempt, *, until: datetime | None = None) -> int:
    started = _aware(attempt.started_at)
    if started is None:
        return 0
    end = until or now()
    return max(int((end - started).total_seconds() * 1000), 0)
