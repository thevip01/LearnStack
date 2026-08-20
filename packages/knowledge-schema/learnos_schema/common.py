"""Primitive types shared by every part of the knowledge schema.

The identifier conventions here are load-bearing. Ids are stable, human readable
and namespaced, because they show up in URLs, in the knowledge graph, in mastery
evidence rows and in authored JSON that humans have to maintain by hand.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

# Dotted, lowercase, kebab-friendly segments: "programming.python",
# "python.functions.closures", "practice.python.functions.code.1"
ID_PATTERN = r"^[a-z0-9]+(?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9]+(?:[-a-z0-9]*[a-z0-9])?)*$"

Id = Annotated[str, StringConstraints(pattern=ID_PATTERN, min_length=2, max_length=200)]

# Subject package version: calendar versioned, "2026.08.0"
VERSION_PATTERN = r"^\d{4}\.\d{2}\.\d+$"
PackageVersion = Annotated[str, StringConstraints(pattern=VERSION_PATTERN)]

Difficulty = Annotated[int, Field(ge=1, le=10)]
Score = Annotated[float, Field(ge=0.0, le=1.0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def slug(text: str) -> str:
    """Best-effort conversion of free text into a single id segment."""
    out = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return re.sub(r"-{2,}", "-", out).strip("-")


class SchemaModel(BaseModel):
    """Base for every schema model.

    ``extra="forbid"`` is deliberate: authored content and LLM-extracted content
    both flow through these models, and silently dropping an unknown key is how
    you end up shipping a subject package where half the hints are missing.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LifecycleStatus(str, Enum):
    """Nothing reaches a learner without passing through review."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class LearningMode(str, Enum):
    LEARN = "learn"
    PRACTICE = "practice"
    LAB = "lab"
    PROJECT = "project"
    PRODUCTION = "production"
    EXAM = "exam"
    REVIEW = "review"


class MasteryDimension(str, Enum):
    """The axes a skill is scored on.

    Kept deliberately small. Each dimension must be measurable by at least one
    kind of practice, otherwise it can never be filled in and the overall score
    is permanently capped.
    """

    CONCEPT = "concept"
    PRACTICE = "practice"
    LAB = "lab"
    DEBUGGING = "debugging"
    PRODUCTION = "production"
    RETENTION = "retention"


class SourceType(str, Enum):
    DOCUMENTATION = "documentation"
    API_REFERENCE = "api_reference"
    ARCHITECTURE = "architecture"
    STANDARD = "standard"
    RFC = "rfc"
    REPOSITORY = "repository"
    TUTORIAL = "tutorial"
    ARTICLE = "article"
    BOOK = "book"
    DATASET = "dataset"
    COURSE = "course"
    FIRST_PARTY = "first_party"


class RuntimeKind(str, Enum):
    PYTHON = "python"
    NODE = "node"
    BROWSER = "browser"
    SQL = "sql"
    BASH = "bash"
    TERRAFORM = "terraform"
    NOTEBOOK = "notebook"
    CLOUD_SIM = "cloud_sim"
    MARKET_SIM = "market_sim"
    NONE = "none"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class SourceRef(SchemaModel):
    """Where a claim came from.

    Every concept, question and best-practice bullet carries these. Without them
    the admin can never answer "where did this statement come from?", and an
    unanswerable version of that question is what makes a learning platform
    untrustworthy for infrastructure and financial content.
    """

    source_id: Id = Field(description="Key into the source registry.")
    url: str | None = None
    title: str | None = None
    source_type: SourceType = SourceType.DOCUMENTATION
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    content_hash: str | None = Field(
        default=None, description="Hash of the chunk this was derived from; drives change detection."
    )
    locator: str | None = Field(
        default=None, description="Anchor, heading path, page number or line range within the source."
    )
    confidence: Confidence = 1.0


class Provenance(SchemaModel):
    """How a piece of content was produced, and whether a human signed off."""

    generator: str = Field(default="human", description="'human', or 'llm:<model>', or 'rule:<name>'.")
    generated_at: datetime = Field(default_factory=utcnow)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: LifecycleStatus = LifecycleStatus.DRAFT
    notes: str | None = None

    @property
    def is_learner_visible(self) -> bool:
        return self.status in (LifecycleStatus.APPROVED, LifecycleStatus.PUBLISHED)
