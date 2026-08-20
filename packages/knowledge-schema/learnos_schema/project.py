"""Projects and assessments."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import Difficulty, Id, MasteryDimension, Provenance, SchemaModel, Score, SourceRef
from .practice import Evaluation, SandboxLimits, SourceFile, TestCase


class Milestone(SchemaModel):
    id: Id
    title: str
    description_md: str
    tests: list[TestCase] = Field(default_factory=list)
    skills: list[Id] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0.0)

    def sanitized(self) -> dict:
        data = self.model_dump(mode="json")
        data["tests"] = [t.sanitized().model_dump(mode="json") for t in self.tests]
        return data


class Project(SchemaModel):
    """A project is a multi-skill deliverable, possibly spanning subjects.

    ``required_skills`` may reference skills from other subject packages. That is
    the mechanism behind cross-subject projects: one build trains several domains
    and posts evidence to all of them.
    """

    id: Id
    title: str
    subject_id: Id
    summary: str
    brief_md: str = Field(description="The full statement of work, as a client would give it.")
    difficulty: Difficulty = 7
    estimated_hours: float = Field(default=4.0, gt=0.0, le=200.0)

    requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list, description="Prevents scope creep in self-directed work.")

    required_skills: list[Id] = Field(default_factory=list)
    taught_skills: list[Id] = Field(default_factory=list)
    cross_subject_skills: list[Id] = Field(
        default_factory=list, description="Skills owned by other subject packages that this project also exercises."
    )
    prerequisite_projects: list[Id] = Field(default_factory=list)

    environment: SandboxLimits = Field(default_factory=SandboxLimits)
    starter_files: list[SourceFile] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    evaluation: Evaluation = Field(
        default_factory=lambda: Evaluation(strategy="rubric", dimension=MasteryDimension.LAB, pass_threshold=0.7)
    )
    stretch_goals: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)

    def sanitized(self) -> dict:
        data = self.model_dump(mode="json")
        data["milestones"] = [m.sanitized() for m in self.milestones]
        data["starter_files"] = [f.model_dump(mode="json") for f in self.starter_files if not f.hidden]
        return data


class AssessmentSection(SchemaModel):
    """One dimension's worth of an assessment.

    An assessment that only asks concept questions can only ever report concept
    understanding, so sections are typed by dimension and a blueprint is required
    to cover more than one.
    """

    id: Id
    title: str
    dimension: MasteryDimension
    practice_ids: list[Id] = Field(min_length=1)
    weight: float = Field(gt=0.0, le=1.0)
    time_limit_s: int | None = None


class Assessment(SchemaModel):
    id: Id
    title: str
    subject_id: Id
    scope: Literal["module", "track", "skill", "subject"] = "module"
    scope_id: Id | None = None
    skills: list[Id] = Field(default_factory=list)
    sections: list[AssessmentSection] = Field(min_length=1)
    pass_threshold: Score = 0.7
    time_limit_s: int | None = None
    max_attempts: int | None = None
    cooldown_hours: int | None = Field(
        default=None, description="Forces spacing between attempts so retries measure learning, not memory."
    )
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def _section_weights(self) -> "Assessment":
        total = sum(s.weight for s in self.sections)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"assessment {self.id!r} section weights sum to {total}, expected 1.0")
        return self
