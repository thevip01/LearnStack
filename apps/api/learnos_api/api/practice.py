"""Practice routes.

Route order matters here: ``/practice/queue`` is declared before
``/practice/{task_id}`` because task ids are dotted strings and ``queue`` would
otherwise be swallowed by the path parameter.

The router is deliberately thin. It resolves the task, resolves the attempt,
checks that the two belong together, and hands off to ``practice.submit``. It does
not grade, does not touch mastery and does not compose feedback — every one of
those lives behind the pipeline so that all seven task kinds cannot diverge.

Two things it *does* own:

* **Serialisation of a task is always ``sanitized()``.** No response model is
  declared, because declaring one would mean restating the shape and giving a
  future edit a place to reintroduce an ``answer`` field.
* **The recommendation attached to a submission.** ``submit`` returns
  ``next=None`` by contract; the recommender needs a learner view the pipeline has
  no business assembling, so the route fills it in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query, status
from pydantic import BaseModel, Field

from ..errors import Conflict, NotFound
from ..modules import practice, progress
from ..modules.auth.deps import CurrentUser, OptionalUser
from ..modules.subjects import assemble
from ..schemas.practice import AttemptOut, HintOut, PracticeQueueOut, SubmissionResultOut, SubmitIn
from .deps import ExecutionDep, RegistryDep, SessionDep, resolve_subject

router = APIRouter(prefix="/practice", tags=["practice"])


class HintRequestIn(BaseModel):
    """Body for the hint route.

    ``level`` is optional; omitting it takes the next unrevealed rung. Naming a
    higher level is allowed and charges for every rung up to it, which is why this
    is a POST and not a GET — see ``attempts.reveal_hint``.
    """

    level: int | None = Field(default=None, ge=1, le=10)


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


@router.get("/queue", response_model=PracticeQueueOut)
async def queue(
    registry: RegistryDep,
    session: SessionDep,
    user: OptionalUser,
    subject_id: str | None = Query(default=None),
    skill_id: str | None = Query(default=None),
    limit: int = Query(10, ge=1, le=100),
) -> PracticeQueueOut:
    """Practice tasks, optionally narrowed to a subject or a skill.

    Ordered easiest-first within a subject. The adaptive ordering lives in
    ``/subjects/{id}/next``; this endpoint is the browsable list, and a list that
    reshuffles itself as mastery moves is a list nobody can find anything in
    twice.
    """
    subjects = [resolve_subject(registry, subject_id)] if subject_id else registry.all_subjects()

    summaries = []
    for subject in subjects:
        stats = (
            await practice.attempt_stats(session, user_id=user.id, subject_id=subject.package.id)
            if user is not None
            else {}
        )
        for task in sorted(subject.package.practice.values(), key=lambda item: (item.difficulty, item.id)):
            if skill_id is not None and skill_id not in task.skills:
                continue
            state, best, count = stats.get(task.id, ("untouched", None, 0))
            summaries.append(assemble.practice_summary(task, state=state, best_score=best, attempts=count))
            if len(summaries) >= limit:
                return PracticeQueueOut(tasks=summaries)

    return PracticeQueueOut(tasks=summaries)


# ---------------------------------------------------------------------------
# One task
# ---------------------------------------------------------------------------


@router.get("/{task_id}")
async def get_task(task_id: str, registry: RegistryDep) -> dict[str, Any]:
    """The task as the learner may see it.

    No ``response_model``: ``sanitized()`` is the contract, and FastAPI filtering
    the dict through a second declaration is exactly the drift this avoids.
    """
    _, task = registry.task(task_id)
    return task.sanitized()


@router.post("/{task_id}/attempts", response_model=AttemptOut, status_code=status.HTTP_201_CREATED)
async def start_attempt(
    task_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: CurrentUser,
) -> AttemptOut:
    """Open an attempt, or hand back the one already open.

    Idempotent on purpose. A learner who reloads the page mid-task must not lose
    the hints they have already paid for, and a second in-progress attempt on the
    same task is a second answer to "how many hints did this cost".
    """
    subject_id, task = registry.task(task_id)
    attempt = await practice.open_attempt(session, user_id=user.id, subject_id=subject_id, task=task)
    return practice.attempt_out(attempt, task)


@router.post("/{task_id}/attempts/{attempt_id}/hint", response_model=HintOut)
async def take_hint(
    task_id: str,
    attempt_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: CurrentUser,
    body: HintRequestIn = Body(default_factory=HintRequestIn),
) -> HintOut:
    _, task = registry.task(task_id)
    attempt = await _attempt_for(session, attempt_id=attempt_id, user_id=user.id, task_id=task_id)
    return await practice.reveal_hint(session, attempt=attempt, task=task, level=body.level)


@router.post("/{task_id}/attempts/{attempt_id}/submit", response_model=SubmissionResultOut)
async def submit(
    task_id: str,
    attempt_id: str,
    payload: SubmitIn,
    registry: RegistryDep,
    session: SessionDep,
    execution: ExecutionDep,
    user: CurrentUser,
) -> SubmissionResultOut:
    subject_id, task = registry.task(task_id)
    subject = resolve_subject(registry, subject_id)
    attempt = await _attempt_for(session, attempt_id=attempt_id, user_id=user.id, task_id=task_id)

    result = await practice.submit(
        session,
        user_id=user.id,
        subject=subject,
        task=task,
        payload=payload,
        attempt=attempt,
        execution=execution,
    )

    # The pipeline returns ``next=None`` because the recommender needs a learner
    # view assembled from four more queries, and making every submission pay for
    # those inside the grading path would couple the two.
    view = await progress.learner_view(session, user_id=user.id, package=subject.package)
    suggestion = progress.next_up(
        subject.package,
        concept_order=subject.concept_order,
        view=view,
        exclude_task_id=task_id,
    )
    return result.model_copy(update={"next": suggestion})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _attempt_for(session, *, attempt_id: str, user_id, task_id: str):
    """Load an attempt and refuse it if it cannot accept more work.

    ``load_attempt`` already scopes to the caller, so the task check is not an
    ownership check — it stops a client from posting task B's answer against task
    A's attempt, which would file the evidence under the wrong skill.

    A ``failed`` attempt is still open for business: an attempt is a working
    session that closes only on a pass, which is what keeps the hint ledger from
    being reset by a deliberate failure.
    """
    attempt = await practice.load_attempt(session, attempt_id, user_id=user_id)
    if attempt.task_id != task_id:
        raise NotFound("attempt not found", {"reason": "attempt_task_mismatch"})
    if attempt.state == "passed":
        raise Conflict(
            "you have already passed this attempt; start a new one to practise it again",
            {"reason": "attempt_passed"},
        )
    return attempt
