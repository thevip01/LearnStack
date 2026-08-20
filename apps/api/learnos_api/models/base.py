"""Declarative base and the column conventions every table follows.

Portable column types are used on purpose: ``sqlalchemy.Uuid`` renders as native
``uuid`` on Postgres and ``CHAR(32)`` on SQLite, and ``JSONVariant`` is ``jsonb``
on Postgres and ``json`` elsewhere. That is what lets the API smoke tests run
against aiosqlite while production runs on Postgres, without a second set of
models to keep in sync.

The only Postgres-only structures are the search index's generated ``tsvector``
columns and the optional ``pgvector`` column, which are added by DDL in
``modules/knowledge/search.py`` rather than declared here — see the note there
about Alembic autogenerate not seeing them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, JSON, Text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# One shared instance is fine: SQLAlchemy type objects are immutable descriptors.
JSONVariant = JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")

#: Dialect-aware UUID. Native on Postgres, CHAR(32) on SQLite.
UuidType = sa.Uuid(as_uuid=True)

#: Length cap for ``learnos_schema.common.Id`` values stored as columns.
ID_LEN = 200


class Base(DeclarativeBase):
    """Metadata holder. Alembic autogenerates against ``Base.metadata``."""


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary keys, generated client-side.

    Client-side generation lets a caller reference a row it is about to insert —
    an attempt id inside a submission, an execution id inside a submission row —
    without a round trip to read back a sequence.
    """
    return mapped_column(UuidType, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
