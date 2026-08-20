"""Subject manifest: the entry point of a subject package."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .common import Id, LearningMode, LifecycleStatus, MasteryDimension, PackageVersion, RuntimeKind, SchemaModel, utcnow


class RuntimeSpec(SchemaModel):
    """A sandbox the subject needs.

    ``image`` must be a pinned tag that exists in the platform's registry. A
    subject package cannot introduce a new runtime by itself; asking for one is a
    platform change, reviewed as such.
    """

    id: str
    kind: RuntimeKind
    version: str
    image: str = Field(description="Pinned runner image, e.g. 'learnos/runner-python:3.12'.")
    default_command: str
    packages: list[str] = Field(default_factory=list, description="Preinstalled in the image, documented here.")
    supports_tests: bool = True
    supports_interactive: bool = False


class DomainRef(SchemaModel):
    id: Id
    title: str
    icon: str | None = None


class SubjectManifest(SchemaModel):
    schema_version: str = Field(default="1.0")

    id: Id = Field(description="'<domain>.<subject>' or '<domain>.<subject>.<provider>'.")
    domain: DomainRef
    subject: str
    provider: str | None = Field(default=None, description="AWS, Azure, GCP for cloud; null for most subjects.")
    title: str
    subtitle: str | None = None
    description: str

    version: PackageVersion
    status: LifecycleStatus = LifecycleStatus.DRAFT
    supersedes: PackageVersion | None = None

    modes: list[LearningMode] = Field(min_length=1)
    runtimes: list[RuntimeSpec] = Field(default_factory=list)
    dimension_weights: dict[MasteryDimension, float] | None = Field(
        default=None, description="Subject-level override of the platform default mastery mix."
    )

    ui_file: str = "ui.json"
    curriculum_file: str = "curriculum.json"
    concepts_dir: str = "concepts"
    practice_dir: str = "practice"
    projects_dir: str = "projects"
    assessments_dir: str = "assessments"
    labs_dir: str = "labs"
    sources_file: str = "sources.json"

    prerequisite_subjects: list[Id] = Field(
        default_factory=list, description="Subjects a learner should already have, e.g. python before machine-learning."
    )
    related_subjects: list[Id] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None
    content_hash: str | None = Field(default=None, description="Hash of every file in the package. Set at build time.")
    refresh_interval_days: int | None = Field(
        default=30, description="How often ingestion should re-check sources for this subject."
    )

    @model_validator(mode="after")
    def _id_matches_parts(self) -> "SubjectManifest":
        expected = ".".join(part for part in (self.domain.id, self.subject, self.provider) if part)
        if self.id != expected:
            raise ValueError(f"manifest id {self.id!r} does not match derived id {expected!r}")
        return self

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "SubjectManifest":
        if self.dimension_weights:
            total = sum(self.dimension_weights.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"dimension_weights sum to {total}, expected 1.0")
        return self

    @model_validator(mode="after")
    def _published_needs_hash(self) -> "SubjectManifest":
        if self.status is LifecycleStatus.PUBLISHED and not self.content_hash:
            raise ValueError("a published manifest must carry a content_hash")
        return self
