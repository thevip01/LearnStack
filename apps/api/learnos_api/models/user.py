"""Users, subject versions and enrolment."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_LEN, Base, TimestampMixin, UuidType, uuid_pk


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SubjectVersion(TimestampMixin, Base):
    """One row per package version the process has ever loaded.

    The spec calls the subject's own dotted id ``id``; it is stored as
    ``subject_id`` here so that every table in the schema can keep a UUID
    primary key called ``id``. ``status`` is the manifest lifecycle status, and
    ``problems`` holds the validation failures for a package that was rejected,
    which is what ``/admin/subjects/reload`` reports.
    """

    __tablename__ = "subject_versions"
    __table_args__ = (UniqueConstraint("subject_id", "content_hash", name="uq_subject_versions_subject_hash"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    load_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserSubjectEnrollment(TimestampMixin, Base):
    """A learner's relationship with a subject.

    ``pinned_content_hash`` exists so that a package refresh cannot change the
    tests under a learner mid-project. Phase 1 records it; honouring it during
    grading is phase 2 and the pipeline reads the live package today.
    """

    __tablename__ = "user_subject_enrollment"
    __table_args__ = (UniqueConstraint("user_id", "subject_id", name="uq_enrollment_user_subject"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    pinned_content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    goal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    minutes_practised: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
