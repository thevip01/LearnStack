"""The search index table.

Everything searchable (concepts, practice tasks, projects, skills, subjects) is
denormalised into one row per entity so that a single query ranks across kinds.
Rebuilt from scratch on package load; it is a projection, never a source.

Three text fields are indexed separately rather than concatenated:

* ``title`` gets trigram similarity, so a typo or a partial word still matches.
* ``search_text`` (title + keywords + summary + definition) gets a weighted
  ``tsvector``.
* ``error_text`` (every ``CommonError.error`` string joined) gets its *own*
  ``tsvector``, because the highest-value search on a learning platform is a
  learner pasting a stack trace. Folding it into the body vector would bury it
  under prose.

The generated ``tsvector`` columns, the GIN/trigram indexes and the optional
``pgvector`` column are added by DDL in ``modules/knowledge/search.py`` rather
than declared here, so that ``create_all`` still works on a plain Postgres
without the extensions and on SQLite in tests.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_LEN, Base, TimestampMixin, uuid_pk


class ConceptIndex(TimestampMixin, Base):
    __tablename__ = "concept_index"
    __table_args__ = (
        UniqueConstraint("entity_id", "entity_kind", name="uq_concept_index_entity"),
        Index("ix_concept_index_subject_kind", "subject_id", "entity_kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    #: "concept" | "practice" | "project" | "skill" | "subject"
    entity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    definition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Everything the weighted lexical vector is built from, materialised so the
    #: generated column expression stays short and the fallback ILIKE ranker used
    #: on SQLite has one column to scan.
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Snippet returned in results. Precomputed so ranking never has to re-read
    #: the package from disk.
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Static importance nudge: a concept outranks the practice task that drills it
    #: when both match equally well.
    boost: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
