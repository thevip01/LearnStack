"""Ingestion tables.

The API owns this schema even though the ingestion service is what writes to it:
one owner of DDL, one Alembic history. Column names are identical to the Pydantic
field names in ``learnos_schema.ingestion`` so that a row round-trips through the
model without a translation layer, and so that the pipeline author does not have
to look anything up.

Two deliberate deviations, both documented rather than silent:

* ``ingestion_documents`` merges ``RawDocument`` and ``ParsedDocument``. The
  architecture lists five ingestion tables, and parse output is one-to-one with a
  fetched document, so the parsed fields hang off the same row. Where the two
  models collide, the raw field keeps the plain name and the parsed one is
  prefixed: ``parsed_id``, ``parsed_content_hash``.
* Primary keys here are the pipeline's own string ids, not UUIDs, because those
  ids are content-derived and are what ``chunk_ids`` and ``document_id``
  reference across stage boundaries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_LEN, Base, JSONVariant, TimestampMixin

DOC_ID_LEN = 128


class IngestionSource(TimestampMixin, Base):
    """Mirrors ``learnos_schema.ingestion.SourceSpec``."""

    __tablename__ = "ingestion_sources"

    id: Mapped[str] = mapped_column(String(ID_LEN), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entrypoint: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    is_first_party: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    license: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Serialised ``FetchPolicy``. Stored whole because it is only ever read by the
    #: fetcher as a unit, and splitting it would make adding a policy knob a migration.
    policy: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestionRun(TimestampMixin, Base):
    """Mirrors ``learnos_schema.ingestion.IngestionRun``."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingestion_runs_subject_started", "subject_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(DOC_ID_LEN), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    source_ids: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    target_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: List of serialised ``StageReport``. The run is a document, not a join target.
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")


class IngestionDocument(TimestampMixin, Base):
    """``RawDocument`` fields, plus ``ParsedDocument`` fields once parsed."""

    __tablename__ = "ingestion_documents"
    __table_args__ = (Index("ix_ingestion_documents_source_hash", "source_id", "content_hash"),)

    id: Mapped[str] = mapped_column(String(DOC_ID_LEN), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("ingestion_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False, default="text/html")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Hash of the raw bytes. Change detection compares this, which is what turns a
    #: source refresh into a diff instead of a rebuild.
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # --- ParsedDocument ---
    parsed_id: Mapped[str | None] = mapped_column(String(DOC_ID_LEN), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    code_blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)


class IngestionChunk(TimestampMixin, Base):
    """Mirrors ``learnos_schema.ingestion.Chunk``."""

    __tablename__ = "ingestion_chunks"
    __table_args__ = (Index("ix_ingestion_chunks_document_ordinal", "document_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(DOC_ID_LEN), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(DOC_ID_LEN), ForeignKey("ingestion_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionCandidate(TimestampMixin, Base):
    """Mirrors ``learnos_schema.ingestion.ExtractionCandidate``.

    ``payload`` is a plain JSON blob on purpose. A candidate that fails schema
    validation still has to be persisted so a reviewer can see *why*, so this
    column must accept content the rest of the platform would reject.
    """

    __tablename__ = "ingestion_candidates"
    __table_args__ = (
        Index("ix_ingestion_candidates_subject_status", "subject_id", "status"),
        Index("ix_ingestion_candidates_subject_target", "subject_id", "target"),
    )

    id: Mapped[str] = mapped_column(String(DOC_ID_LEN), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(ID_LEN), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    chunk_ids: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    duplicate_of: Mapped[str | None] = mapped_column(String(ID_LEN), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
