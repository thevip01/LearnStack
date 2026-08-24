"""Progress: append-only evidence, plus caches derived from it.

``mastery_evidence`` is the only table in this schema that is authoritative about
what a learner knows, and it is append-only. Nothing updates a score in place.
That is what makes it possible to change the mastery maths (decay half-life,
hint penalty, dimension weights) and recompute history rather than migrate it,
and it is why a grader bug is recoverable.

``user_skill_state`` is a cache of the rollup plus the two pieces of adaptive
state that genuinely are state rather than derivation: ``ability`` (an Elo-style
running estimate) and ``consecutive_failures``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_LEN, Base, JSONVariant, TimestampMixin, UuidType, uuid_pk


class MasteryEvidence(Base):
    """One observation. Mirrors ``learnos_schema.mastery.Evidence`` field for field.

    No ``updated_at``: rows are never updated. ``created_at`` is the observation
    time and feeds the recency decay, so it is set explicitly by the writer rather
    than defaulted by the database: replaying historical evidence has to be able
    to backdate.
    """

    __tablename__ = "mastery_evidence"
    __table_args__ = (
        Index("ix_evidence_user_subject_skill", "user_id", "subject_id", "skill_id"),
        Index("ix_evidence_user_skill_dim_created", "user_id", "skill_id", "dimension", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(ID_LEN), nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class UserSkillState(TimestampMixin, Base):
    """Derived rollup plus adaptive state, one row per (user, skill)."""

    __tablename__ = "user_skill_state"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_user_skill_state"),
        Index("ix_user_skill_state_user_subject", "user_id", "subject_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    overall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: ``{dimension: {"score": float, "measured": bool, "evidence_count": int}}``.
    #: ``measured: false`` is not the same as ``score: 0`` and the UI must render
    #: it as a dash; keeping the flag in the cached blob preserves that.
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="untouched")
    ability: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProgressEvent(Base):
    """Append-only activity log: streaks, history and time-on-task come from here.

    Deliberately separate from ``mastery_evidence``: viewing a lesson is activity
    and belongs here, but it is not evidence of skill and must never reach the
    mastery rollup.
    """

    __tablename__ = "progress_events"
    __table_args__ = (Index("ix_progress_events_user_subject_time", "user_id", "subject_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(ID_LEN), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


#: Event kinds in use. Kept as a tuple rather than an enum column so that adding
#: one is not a migration.
EVENT_CONCEPT_VIEWED = "concept_viewed"
EVENT_PRACTICE_SUBMITTED = "practice_submitted"
EVENT_PRACTICE_PASSED = "practice_passed"
EVENT_PROJECT_COMPLETED = "project_completed"
EVENT_ASSESSMENT_COMPLETED = "assessment_completed"
EVENT_HINT_TAKEN = "hint_taken"
