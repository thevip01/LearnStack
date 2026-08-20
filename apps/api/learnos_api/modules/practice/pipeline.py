"""The submission pipeline: one path from posted payload to graded response.

Every practice kind funnels through :func:`submit`. That is the point of the
``GradeOutcome`` shape — after ``_grade`` returns, nothing in this file knows or
cares whether the learner wrote Python, drew a diagram or answered a quiz. The
steps are always the same:

1. Check the payload's ``kind`` against the authored task's kind.
2. Grade (pure, or via the sandbox).
3. Snapshot mastery *before*, write evidence, snapshot *after* — so the deltas
   the UI animates are measured rather than predicted.
4. Update ability and the failure counter, log activity, invalidate the cache.
5. Decide what may now be revealed, and what to suggest next.

Ordering note: evidence is written before the "after" snapshot is computed, and
both happen inside the request's transaction. If the commit fails, the learner
sees an error and no mastery moved — which is the only honest failure mode. A
design that returned the response first and persisted afterwards would show
progress that does not exist.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from learnos_schema import (
    ArchitectureTask,
    CodeTask,
    DebugTask,
    IncidentTask,
    PracticeTask,
    QuizTask,
    SkillMastery,
    SQLTask,
    SubjectPackage,
    TerminalTask,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import BadRequest
from ...logging import get_logger
from ...models import EVENT_HINT_TAKEN, EVENT_PRACTICE_PASSED, EVENT_PRACTICE_SUBMITTED, Attempt, ProgressEvent
from ...schemas.practice import (
    MasteryDeltaOut,
    RevealOut,
    SubmissionResultOut,
    SubmittedFile,
)
from ..execution.service import ExecutionService
from ..knowledge.readiness import is_ready
from ..progress import evidence as evidence_mod
from ..progress import rollup
from ..subjects.assemble import enum_value
from ..subjects.registry import LoadedSubject
from . import attempts as attempts_mod
from . import code as code_mod
from . import design as design_mod
from . import quiz as quiz_mod
from . import sql as sql_mod
from . import terminal as terminal_mod
from .results import GradeOutcome

log = get_logger(__name__)


def task_kind(task: PracticeTask) -> str:
    return enum_value(getattr(task, "kind", "")) or ""


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def _grade(
    task: PracticeTask,
    payload: Any,
    *,
    execution: ExecutionService,
    execution_id: str | None,
) -> GradeOutcome:
    kind = task_kind(task)
    posted = enum_value(getattr(payload, "kind", ""))
    if posted != kind:
        raise BadRequest(
            f"this task is a {kind} task; the submission says {posted!r}",
            {"reason": "task_kind_mismatch", "expected": kind, "received": posted},
        )

    if isinstance(task, QuizTask):
        return quiz_mod.grade_quiz(task, payload.answers)
    if isinstance(task, DebugTask):
        return await code_mod.grade_debug(
            task, [file.model_dump() for file in payload.files], execution=execution, execution_id=execution_id
        )
    if isinstance(task, CodeTask):
        return await code_mod.grade_code(
            task, [file.model_dump() for file in payload.files], execution=execution, execution_id=execution_id
        )
    if isinstance(task, SQLTask):
        return await sql_mod.grade_sql(task, payload.sql, execution=execution, execution_id=execution_id)
    if isinstance(task, TerminalTask):
        return await terminal_mod.grade_terminal(
            task, payload.commands, execution=execution, execution_id=execution_id
        )
    if isinstance(task, ArchitectureTask):
        return design_mod.grade_architecture(task, payload.nodes, payload.edges)
    if isinstance(task, IncidentTask):
        return design_mod.grade_incident(
            task,
            inspected=payload.inspected,
            remediations=payload.remediations,
            root_cause=payload.root_cause,
        )
    # Unreachable while the discriminated union and the schema union agree. If a
    # new kind is added to one and not the other, failing loudly here is far
    # better than grading it as zero.
    raise BadRequest(f"{kind!r} tasks cannot be submitted", {"reason": "unsupported_task_kind", "kind": kind})


# ---------------------------------------------------------------------------
# Deltas and reveals
# ---------------------------------------------------------------------------


def mastery_deltas(
    package: SubjectPackage,
    *,
    skill_ids: Sequence[str],
    dimension: str,
    before: dict[str, SkillMastery],
    after: dict[str, SkillMastery],
) -> list[MasteryDeltaOut]:
    """One row per skill the task claims, with measured before/after values."""
    index = package.curriculum.skill_index()
    deltas: list[MasteryDeltaOut] = []
    for skill_id in skill_ids:
        skill = index.get(skill_id)
        post = after.get(skill_id)
        if post is None:
            continue
        pre = before.get(skill_id)
        deltas.append(
            MasteryDeltaOut(
                skill_id=skill_id,
                title=skill.title if skill else skill_id,
                dimension=dimension,  # type: ignore[arg-type]
                before=round(pre.overall, 4) if pre else 0.0,
                after=round(post.overall, 4),
                state=post.state,  # type: ignore[arg-type]
            )
        )
    return deltas


def newly_unlocked(
    package: SubjectPackage,
    *,
    before: dict[str, SkillMastery],
    after: dict[str, SkillMastery],
) -> list[str]:
    """Skills that were blocked by a prerequisite before this submission and are not now.

    Only the skills whose gate actually moved. Recomputing readiness for the whole
    subject is cheap (it is pure, over data already in memory) and far more
    trustworthy than trying to infer the affected subgraph.
    """
    unlocked: list[str] = []
    for skill in package.curriculum.skills:
        if not skill.prerequisites:
            continue
        if not is_ready(package, skill.id, before) and is_ready(package, skill.id, after):
            unlocked.append(skill.id)
    return unlocked


def reveal_for(task: PracticeTask, *, passed: bool, solution_revealed: bool) -> RevealOut | None:
    """What the learner has earned the right to see.

    Two ways to earn it: pass the task, or take the hint that explicitly says it
    gives the answer away. Anything else and the answer-bearing fields stay on the
    server, which is the whole reason ``sanitized()`` exists.
    """
    if not (passed or solution_revealed):
        return None

    if isinstance(task, IncidentTask):
        return RevealOut(
            root_cause_md=task.root_cause_md,
            correct_remediations=list(task.correct_remediations) or None,
        )
    solution_files = getattr(task, "solution_files", None)
    if solution_files:
        return RevealOut(
            solution_files=[SubmittedFile(path=source.path, content=source.content) for source in solution_files]
        )
    return None


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


async def submit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject: LoadedSubject,
    task: PracticeTask,
    payload: Any,
    attempt: Attempt,
    execution: ExecutionService,
) -> SubmissionResultOut:
    package = subject.package
    dimension = enum_value(task.evaluation.dimension)
    started = attempts_mod.now()

    before = await rollup.mastery_lookup(
        session, user_id=user_id, subject_id=package.manifest.id, package=package
    )

    execution_id = str(uuid.uuid4())
    outcome = await _grade(task, payload, execution=execution, execution_id=execution_id)
    duration_ms = int((attempts_mod.now() - started).total_seconds() * 1000)

    execution_row_id: uuid.UUID | None = None
    if outcome.execution is not None:
        row = await execution.record(
            session,
            outcome.execution,
            user_id=user_id,
            runtime=enum_value(getattr(getattr(task, "environment", None), "runtime", "python")),
            task_id=task.id,
        )
        execution_row_id = row.id

    submission = await attempts_mod.record_submission(
        session,
        attempt=attempt,
        dimension=dimension,
        payload=payload,
        outcome=outcome,
        duration_ms=duration_ms,
        execution_id=execution_row_id,
    )

    hints_used = int(attempt.hints_used or 0)
    evidence_mod.persist_evidence(
        session,
        user_id=user_id,
        subject_id=package.manifest.id,
        evidence=evidence_mod.evidence_for_task(
            task, score=outcome.score, hints_used=hints_used, source_type="practice"
        ),
    )
    await session.flush()

    after = await rollup.mastery_lookup(
        session, user_id=user_id, subject_id=package.manifest.id, package=package
    )
    await rollup.sync_skill_states(session, user_id=user_id, subject_id=package.manifest.id, masteries=after)
    await rollup.apply_attempt_outcome(
        session,
        user_id=user_id,
        subject_id=package.manifest.id,
        skill_ids=task.skills,
        difficulty=task.difficulty,
        score=outcome.score,
        passed=outcome.passed,
        at=submission.graded_at,
    )

    session.add(
        ProgressEvent(
            user_id=user_id,
            subject_id=package.manifest.id,
            kind=EVENT_PRACTICE_PASSED if outcome.passed else EVENT_PRACTICE_SUBMITTED,
            entity_id=task.id,
            payload={"score": round(outcome.score, 4), "hints_used": hints_used, "kind": task_kind(task)},
            minutes=round(duration_ms / 60_000, 3),
            occurred_at=submission.graded_at,
        )
    )
    if hints_used and int(attempt.submission_count or 0) == 1:
        # Logged once per attempt rather than once per hint: the interesting signal
        # is "this task needed help", and one row per level would drown the feed.
        session.add(
            ProgressEvent(
                user_id=user_id,
                subject_id=package.manifest.id,
                kind=EVENT_HINT_TAKEN,
                entity_id=task.id,
                payload={"levels": hints_used},
                occurred_at=submission.graded_at,
            )
        )

    await rollup.invalidate(user_id, package.manifest.id)

    return SubmissionResultOut(
        attempt_id=str(attempt.id),
        task_id=task.id,
        passed=outcome.passed,
        score=round(outcome.score, 4),
        dimension=dimension,  # type: ignore[arg-type]
        hints_used=hints_used,
        duration_ms=duration_ms,
        feedback_md=outcome.feedback_md,
        execution=outcome.execution,
        question_results=outcome.question_results,
        mastery_deltas=mastery_deltas(
            package, skill_ids=task.skills, dimension=dimension, before=before, after=after
        ),
        unlocked_skills=newly_unlocked(package, before=before, after=after),
        reveal=reveal_for(task, passed=outcome.passed, solution_revealed=bool(attempt.solution_revealed)),
        next=None,  # filled in by the route, which owns the recommender
    )
