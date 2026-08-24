"""The knowledge graph, as the client draws it.

One graph, two node kinds. Concepts are what a learner reads; skills are what gets
measured. Both are in the same payload because the interesting questions are
cross-kind ("which concept do I read to fix this red skill"), and answering them
client-side would need two fetches and a join the frontend is not allowed to make.

Edge kinds, and why each exists:

* ``prerequisite``: must come before. Drives readiness. Drawn as a hard arrow.
* ``composes``: a concept contributes evidence to a skill. This is the bridge
  between the two node kinds.
* ``analogue``: "this is the AWS equivalent of that GCP thing". Cross-subject and
  the only edge kind allowed to point outside the current package.
* ``evidences``: a skill's dependency on another skill within the curriculum.
"""

from __future__ import annotations

from learnos_schema import SkillMastery, SubjectPackage

from ...schemas.graph import GraphEdgeOut, GraphNodeOut, GraphOut
from .readiness import concept_mastery


def concept_nodes(package: SubjectPackage, masteries: dict[str, SkillMastery] | None) -> list[GraphNodeOut]:
    nodes: list[GraphNodeOut] = []
    for concept in package.concepts.values():
        nodes.append(
            GraphNodeOut(
                id=concept.id,
                kind="concept",
                label=concept.title,
                category=concept.category,
                difficulty=getattr(concept, "difficulty", None),
                skills=list(concept.skills),
                mastery=concept_mastery(concept, masteries) if masteries else None,
            )
        )
    return nodes


def skill_nodes(package: SubjectPackage, masteries: dict[str, SkillMastery] | None) -> list[GraphNodeOut]:
    nodes: list[GraphNodeOut] = []
    for skill in package.curriculum.skills:
        mastery = (masteries or {}).get(skill.id)
        nodes.append(
            GraphNodeOut(
                id=skill.id,
                kind="skill",
                label=skill.title,
                category=getattr(skill, "category", None),
                # ``None`` rather than 0.0 for an unmeasured skill: the UI draws an
                # outline instead of a full-red node, which is the difference
                # between "you are bad at this" and "we have not asked yet".
                mastery=mastery.overall if mastery and mastery.evidence_count > 0 else None,
            )
        )
    return nodes


def edges(package: SubjectPackage) -> list[GraphEdgeOut]:
    out: list[GraphEdgeOut] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key in seen:
            return
        seen.add(key)
        out.append(GraphEdgeOut(source=source, target=target, kind=kind))  # type: ignore[arg-type]

    known_concepts = set(package.concepts)
    for concept in package.concepts.values():
        for prereq in concept.prerequisites:
            if prereq in known_concepts:
                add(prereq, concept.id, "prerequisite")
        for dependency in concept.dependencies:
            if dependency in known_concepts and dependency not in concept.prerequisites:
                add(dependency, concept.id, "prerequisite")
        for skill_id in concept.skills:
            add(concept.id, skill_id, "composes")
        for analogue in concept.analogues:
            # Analogues may point at another subject's concept id. The node will be
            # absent from this payload; the client renders a stub it can follow.
            add(concept.id, analogue, "analogue")

    for skill in package.curriculum.skills:
        for prereq in skill.prerequisites:
            add(prereq, skill.id, "evidences")
    return out


def build(
    package: SubjectPackage,
    *,
    masteries: dict[str, SkillMastery] | None = None,
    include: str = "all",
) -> GraphOut:
    """Assemble the graph.

    ``include`` trims the payload for views that only need one kind: the skill map
    does not need 40 concept nodes, and the concept map does not need the skill
    layer. Edges are filtered to those whose endpoints survived.
    """
    nodes: list[GraphNodeOut] = []
    if include in {"all", "concepts"}:
        nodes += concept_nodes(package, masteries)
    if include in {"all", "skills"}:
        nodes += skill_nodes(package, masteries)

    ids = {node.id for node in nodes}
    kept = [
        edge
        for edge in edges(package)
        # An analogue's target is allowed to be absent: it is a cross-subject
        # pointer by design. Every other edge must connect two rendered nodes.
        if edge.source in ids and (edge.target in ids or edge.kind == "analogue")
    ]
    return GraphOut(nodes=nodes, edges=kept)
