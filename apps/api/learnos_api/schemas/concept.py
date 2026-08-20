"""Concept envelope.

``ConceptOut`` subclasses ``learnos_schema.Concept`` so the payload is the concept
flat, with the runtime's additions alongside it — which is what the contract's
``Concept & {...}`` means. Subclassing rather than nesting also means a new field
on ``Concept`` reaches the client without a change here.
"""

from __future__ import annotations

from learnos_schema import Concept
from pydantic import Field

from .common import ApiModel
from .practice import PracticeSummary


class PrerequisiteStatusOut(ApiModel):
    concept_id: str
    title: str
    #: ``null`` when there is no evidence, or when the caller is anonymous.
    mastery: float | None = None
    #: Advice, never a gate. The platform warns and lets the learner proceed.
    ready: bool = True


class ModuleRefOut(ApiModel):
    id: str
    title: str
    track_id: str
    track_title: str


class ConceptOut(Concept):
    practice: list[PracticeSummary] = Field(default_factory=list)  # type: ignore[assignment]
    prerequisite_status: list[PrerequisiteStatusOut] = Field(default_factory=list)
    next_concept_id: str | None = None
    prev_concept_id: str | None = None
    module: ModuleRefOut | None = None


class CompareRowOut(ApiModel):
    facet: str
    values: dict[str, str | None] = Field(default_factory=dict)


class CompareOut(ApiModel):
    ids: list[str] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)
    rows: list[CompareRowOut] = Field(default_factory=list)
