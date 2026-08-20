"""Attempts, submissions and hint reveals.

An attempt is the unit a learner opens; a submission is one graded push against
it. Keeping them separate is what lets hint usage and elapsed time span several
submissions, and it is why the mastery evidence weight can be discounted for
hints taken long before the successful push.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_LEN, Base, JSONVariant, TimestampMixin, UuidType, uuid_pk

#: Matches ``PracticeSummary.state`` in the contract, minus "untouched" which
#: means "no attempt row exists".
ATTEMPT_STATES = ("in_progress", "passed", "failed")


class Attempt(TimestampMixin, Base):
    __tablename__ = "attempts"
    __table_args__ = (
        # The hot lookup is "does this user have an open attempt on this task".
        Index("ix_attempts_user_task_state", "user_id", "task_id", "state"),
        Index("ix_attempts_user_subject", "user_id", "subject_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    #: True once a ``reveals_solution`` hint has been taken. Drives the contract's
    #: rule that the solution may be revealed on a failed-but-exhausted attempt.
    solution_revealed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (Index("ix_submissions_attempt_graded", "attempt_id", "graded_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The learner's raw submission, exactly as posted. Kept so that a grader fix
    #: can be replayed against historical submissions instead of guessed at.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    feedback_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    per_item_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONVariant, nullable=True)
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("executions.id", ondelete="SET NULL"), nullable=True
    )


class HintReveal(TimestampMixin, Base):
    """Append-only record of which hint levels were taken, and when.

    Stored per reveal rather than as a counter so that a later analysis can ask
    "did the hint help?" by comparing the submissions either side of it.
    """

    __tablename__ = "hint_reveals"
    __table_args__ = (Index("ix_hint_reveals_attempt_level", "attempt_id", "level", unique=True),)

    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    revealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
