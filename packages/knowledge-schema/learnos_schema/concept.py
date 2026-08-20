"""Concepts: the atomic unit of knowledge.

A concept is not a lesson page. It is a normalized description of one idea, with
enough structure that the runtime can render it as a lesson, generate practice
from it, place it in the graph, and cite it.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .common import Id, Provenance, SchemaModel, SourceRef
from .content import ContentBlock


class CommonError(SchemaModel):
    """A mistake learners and practitioners actually make.

    Kept as a first-class field rather than prose because the practice generator
    turns these directly into debugging exercises, and the tutor uses them to
    recognise what a learner has done wrong.
    """

    error: str = Field(description="The symptom, as it appears to the user. Error text, wrong output, or behaviour.")
    cause: str
    fix: str
    sources: list[SourceRef] = Field(default_factory=list)


class Example(SchemaModel):
    title: str
    md: str | None = None
    code: str | None = None
    language: str | None = None
    output: str | None = None


class ConceptComponent(SchemaModel):
    """A named part of a composite concept.

    For "Application Load Balancer" these are listener, target group, health
    check. For "decorator" they are wrapper, wrapped function, closure.
    """

    name: str
    role: str
    required: bool = True


class Concept(SchemaModel):
    id: Id
    title: str
    subject_id: Id = Field(description="Owning subject package, e.g. 'programming.python'.")
    category: str = Field(description="Grouping within the subject, e.g. 'language', 'networking'.")

    summary: str = Field(max_length=400, description="One or two sentences. Used in search results and hover cards.")
    definition: str = Field(description="A precise definition. Should be defensible against the cited sources.")
    purpose: str = Field(description="Why this exists / what problem it solves. Learners retain the why.")

    body: list[ContentBlock] = Field(default_factory=list)

    components: list[ConceptComponent] = Field(default_factory=list)
    dependencies: list[Id] = Field(
        default_factory=list,
        description="Concepts this one is built out of. Structural, not pedagogical, edges in the graph.",
    )
    prerequisites: list[Id] = Field(
        default_factory=list,
        description="Concepts a learner must understand first. Pedagogical edges; drive readiness checks.",
    )
    related: list[Id] = Field(default_factory=list)
    analogues: list[Id] = Field(
        default_factory=list,
        description="Cross-subject equivalents, e.g. AWS ALB <-> Azure Load Balancer. Powers compare mode.",
    )

    common_errors: list[CommonError] = Field(default_factory=list)
    best_practices: list[str] = Field(default_factory=list)
    production_considerations: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)

    skills: list[Id] = Field(default_factory=list, description="Skills this concept contributes evidence toward.")
    practice: list[Id] = Field(default_factory=list, description="Practice task ids attached to this concept.")

    keywords: list[str] = Field(default_factory=list, description="Boosted in keyword search; includes error strings.")
    estimated_minutes: int = Field(default=10, ge=1, le=600)

    sources: list[SourceRef] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def _no_self_reference(self) -> "Concept":
        for field in ("dependencies", "prerequisites", "related", "analogues"):
            if self.id in getattr(self, field):
                raise ValueError(f"concept {self.id!r} lists itself in {field}")
        return self

    @model_validator(mode="after")
    def _must_cite_something(self) -> "Concept":
        cited = bool(self.sources) or any(
            getattr(block, "sources", None) for block in self.body
        )
        if not cited:
            raise ValueError(
                f"concept {self.id!r} has no sources; every concept must be traceable to at least one source"
            )
        return self
