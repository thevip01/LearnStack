"""Ingestion contracts.

The pipeline is Sources -> Fetch -> Parse -> Clean -> Chunk -> Extract ->
Validate -> Review -> Publish. These are the objects that move between stages.

Two rules are encoded here rather than left to convention. Nothing crosses into a
published package without a ``Provenance`` that says who or what produced it and
who reviewed it. And every ``Chunk`` keeps its ``content_hash``, because that is
what makes a source refresh a diff instead of a rebuild.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import Confidence, Id, LifecycleStatus, Provenance, SchemaModel, SourceType, utcnow


class AdapterKind(str, Enum):
    WEB = "web"
    SITEMAP = "sitemap"
    RSS = "rss"
    GITHUB = "github"
    OPENAPI = "openapi"
    PDF = "pdf"
    LOCAL = "local"


class FetchPolicy(SchemaModel):
    """Crawl politeness, declared per source rather than assumed globally."""

    respect_robots: bool = True
    rate_limit_rps: float = Field(default=0.5, gt=0.0, le=10.0)
    max_pages: int = Field(default=200, ge=1, le=100_000)
    max_depth: int = Field(default=3, ge=0, le=10)
    user_agent: str = "LearnOS-Ingest/0.1 (+https://example.invalid/bot)"
    timeout_s: int = Field(default=20, ge=1, le=300)
    allow_patterns: list[str] = Field(default_factory=list)
    deny_patterns: list[str] = Field(default_factory=list)
    requires_auth: bool = False
    license_ack: str | None = Field(
        default=None, description="Required for anything not obviously permissive. Blocks fetch when missing."
    )


class SourceSpec(SchemaModel):
    """A source attached to a subject, plus how to go and get it."""

    id: Id
    subject_id: Id
    title: str
    adapter: AdapterKind
    source_type: SourceType
    entrypoint: str = Field(description="URL, repo slug, spec URL, or local path depending on the adapter.")
    priority: int = Field(ge=0, le=100)
    is_first_party: bool = False
    license: str | None = None
    policy: FetchPolicy = Field(default_factory=FetchPolicy)
    enabled: bool = True
    last_run_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _first_party_priority(self) -> "SourceSpec":
        if self.is_first_party and self.priority < 80:
            raise ValueError(
                f"source {self.id!r} is first-party but priority {self.priority} would let a blog outrank it"
            )
        return self


class RawDocument(SchemaModel):
    """One fetched artefact, before parsing."""

    id: str
    source_id: Id
    url: str | None = None
    path: str | None = None
    media_type: str = "text/html"
    fetched_at: datetime = Field(default_factory=utcnow)
    http_status: int | None = None
    etag: str | None = None
    last_modified: datetime | None = None
    content_hash: str
    byte_size: int = 0
    raw_ref: str | None = Field(default=None, description="Object-storage key for the raw bytes; not inlined.")


class ParsedDocument(SchemaModel):
    """Cleaned text plus the structure worth keeping."""

    id: str
    document_id: str
    source_id: Id
    title: str | None = None
    canonical_url: str | None = None
    text: str
    heading_path: list[str] = Field(default_factory=list)
    code_blocks: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    published_at: datetime | None = None
    language: str = "en"
    word_count: int = 0
    content_hash: str


class Chunk(SchemaModel):
    """A retrieval unit. Small enough to cite, large enough to mean something."""

    id: str
    document_id: str
    source_id: Id
    subject_id: Id
    ordinal: int = Field(ge=0)
    text: str
    heading_path: list[str] = Field(default_factory=list)
    token_estimate: int = 0
    content_hash: str
    embedding_model: str | None = None
    embedded_at: datetime | None = None


class ExtractionTarget(str, Enum):
    CONCEPT = "concept"
    CURRICULUM = "curriculum"
    PRACTICE = "practice"
    PROJECT = "project"
    ASSESSMENT = "assessment"


class ExtractionRequest(SchemaModel):
    subject_id: Id
    target: ExtractionTarget
    chunks: list[Chunk] = Field(min_length=1)
    hint: str | None = Field(default=None, description="Steering, e.g. 'focus on health-check failure modes'.")
    existing_ids: list[Id] = Field(
        default_factory=list, description="So the extractor can deduplicate rather than re-mint concepts."
    )


class ValidationIssue(SchemaModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    pointer: str | None = Field(default=None, description="JSON pointer into the candidate payload.")


class ExtractionCandidate(SchemaModel):
    """Extractor output, pre-review.

    ``payload`` is a candidate Concept / PracticeTask / etc. It is stored as a
    plain dict on purpose: a candidate that fails schema validation still has to
    be persisted so a reviewer can see what went wrong.
    """

    id: str
    subject_id: Id
    target: ExtractionTarget
    payload: dict
    chunk_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = 0.5
    issues: list[ValidationIssue] = Field(default_factory=list)
    duplicate_of: Id | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    status: LifecycleStatus = LifecycleStatus.DRAFT

    @property
    def is_promotable(self) -> bool:
        """Schema-clean, not a duplicate, and reviewed."""
        return (
            not any(i.severity == "error" for i in self.issues)
            and self.duplicate_of is None
            and self.status in (LifecycleStatus.APPROVED, LifecycleStatus.PUBLISHED)
        )


class IngestionStage(str, Enum):
    FETCH = "fetch"
    PARSE = "parse"
    CLEAN = "clean"
    CHUNK = "chunk"
    EMBED = "embed"
    EXTRACT = "extract"
    VALIDATE = "validate"
    REVIEW = "review"
    BUILD = "build"
    PUBLISH = "publish"


class StageReport(SchemaModel):
    stage: IngestionStage
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    ok: bool = True
    items_in: int = 0
    items_out: int = 0
    skipped: int = 0
    messages: list[str] = Field(default_factory=list)


class IngestionRun(SchemaModel):
    id: str
    subject_id: Id
    source_ids: list[Id] = Field(default_factory=list)
    target_version: str | None = None
    dry_run: bool = True
    stages: list[StageReport] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: Literal["running", "succeeded", "failed", "cancelled"] = "running"

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.stages)


class SourceDiff(SchemaModel):
    """What changed since last time, and what that invalidates.

    The ``affected_*`` lists are the reason this exists: a refresh should
    regenerate the concepts touched by changed chunks and leave the rest of the
    package, and the learner progress attached to it, alone.
    """

    source_id: Id
    added_documents: list[str] = Field(default_factory=list)
    changed_documents: list[str] = Field(default_factory=list)
    removed_documents: list[str] = Field(default_factory=list)
    affected_concepts: list[Id] = Field(default_factory=list)
    affected_practice: list[Id] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=utcnow)

    @property
    def is_empty(self) -> bool:
        return not (self.added_documents or self.changed_documents or self.removed_documents)
