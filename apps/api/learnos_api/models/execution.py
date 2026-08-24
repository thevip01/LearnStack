"""Execution records.

``stdout_ref`` / ``stderr_ref`` are object-storage keys rather than inline text.
Learner output is unbounded in practice (an accidental infinite print loop is a
normal Tuesday), and a row that can grow to the output cap on every submission
makes the table unusable for analytics.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_LEN, Base, JSONVariant, TimestampMixin, UuidType, uuid_pk


class Execution(TimestampMixin, Base):
    __tablename__ = "executions"
    __table_args__ = (Index("ix_executions_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: ``learnos_schema.ExecutionStatus`` value.
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    #: ``RuntimeKind`` value, e.g. "python". Not the image tag; that is in ``image``.
    runtime: Mapped[str] = mapped_column(String(32), nullable=False)
    image: Mapped[str | None] = mapped_column(String(256), nullable=True)
    runner: Mapped[str] = mapped_column(String(16), nullable=False, default="docker")
    task_id: Mapped[str | None] = mapped_column(String(ID_LEN), nullable=True)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    artifacts: Mapped[dict[str, str]] = mapped_column(JSONVariant, nullable=False, default=dict)
    stdout_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stderr_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Platform-level failure text. A learner's failing test is *not* an error.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
