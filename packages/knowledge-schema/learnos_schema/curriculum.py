"""Curriculum and the skill graph.

Two separate structures on purpose:

* ``Track -> Module -> Concept`` is the *navigational* shape. It is what the
  sidebar renders, and it is linear-ish because humans want a path.
* ``Skill`` and its prerequisites are the *dependency* shape. It is a DAG, it is
  what readiness checks and recommendations run on, and it is allowed to
  disagree with the navigation order.

Conflating the two is how course platforms end up unable to answer "what should
I learn next" with anything better than "the next chapter".
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .common import Difficulty, Id, MasteryDimension, SchemaModel


class Module(SchemaModel):
    id: Id
    title: str
    summary: str | None = None
    concepts: list[Id] = Field(default_factory=list)
    projects: list[Id] = Field(default_factory=list)
    labs: list[Id] = Field(default_factory=list)
    assessment_id: Id | None = None
    estimated_minutes: int | None = None
    icon: str | None = None


class Track(SchemaModel):
    """A coherent route through a subject, e.g. 'Core Python' vs 'Async Python'."""

    id: Id
    title: str
    summary: str | None = None
    modules: list[Module] = Field(default_factory=list)
    goal: str | None = Field(default=None, description="What the learner can do at the end. Concrete, not aspirational.")


class Skill(SchemaModel):
    """A capability that can be demonstrated, and therefore scored.

    Skills are what mastery attaches to. Concepts explain; skills are performed.
    """

    id: Id
    title: str
    description: str | None = None
    concepts: list[Id] = Field(default_factory=list)
    prerequisites: list[Id] = Field(default_factory=list, description="Other skill ids that gate this one.")
    difficulty: Difficulty = 5
    dimension_weights: dict[MasteryDimension, float] | None = Field(
        default=None,
        description=(
            "Overrides the subject default. A skill like 'debug an unhealthy target group' should weight "
            "debugging and production heavily; 'name the parts of a function signature' should not."
        ),
    )
    external_analogues: list[Id] = Field(default_factory=list)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "Skill":
        if self.dimension_weights:
            total = sum(self.dimension_weights.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"skill {self.id!r} dimension_weights sum to {total}, expected 1.0")
        return self


class Curriculum(SchemaModel):
    subject_id: Id
    tracks: list[Track] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    default_track: Id | None = None

    def concept_ids(self) -> list[Id]:
        return [c for t in self.tracks for m in t.modules for c in m.concepts]

    def skill_index(self) -> dict[Id, Skill]:
        return {s.id: s for s in self.skills}

    @model_validator(mode="after")
    def _skill_graph_is_acyclic(self) -> "Curriculum":
        index = {s.id: s.prerequisites for s in self.skills}
        unknown = {p for prereqs in index.values() for p in prereqs} - set(index)
        if unknown:
            raise ValueError(f"skill prerequisites reference unknown skills: {sorted(unknown)}")

        WHITE, GREY, BLACK = 0, 1, 2
        colour = dict.fromkeys(index, WHITE)

        def visit(node: str, path: list[str]) -> None:
            colour[node] = GREY
            for nxt in index[node]:
                if colour[nxt] == GREY:
                    cycle = " -> ".join(path + [node, nxt])
                    raise ValueError(f"skill prerequisite cycle: {cycle}")
                if colour[nxt] == WHITE:
                    visit(nxt, path + [node])
            colour[node] = BLACK

        for node in index:
            if colour[node] == WHITE:
                visit(node, [])
        return self

    @model_validator(mode="after")
    def _module_ids_unique(self) -> "Curriculum":
        seen: set[str] = set()
        for track in self.tracks:
            for module in track.modules:
                if module.id in seen:
                    raise ValueError(f"duplicate module id {module.id!r}")
                seen.add(module.id)
        return self
