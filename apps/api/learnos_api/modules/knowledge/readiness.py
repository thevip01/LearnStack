"""Readiness: what is standing between a learner and a skill.

The rule from the contract, in one line: a prerequisite skill blocks when its
``overall < 0.6``, and the platform **warns but never hard-blocks**. Gating
content behind a score is how a learning platform turns a bad estimate into a
locked door; reporting what is missing lets the learner decide.

Readiness runs on the *skill* graph, not the navigation order. The sidebar is
linear because humans want a path; prerequisites are a DAG because knowledge is.
"""

from __future__ import annotations

from learnos_schema import Concept, SkillMastery, SubjectPackage

from ...schemas.concept import PrerequisiteStatusOut
from ...schemas.graph import BlockingSkillOut, ReadinessOut

#: Contractual. A prerequisite below this blocks; at or above it does not.
READINESS_THRESHOLD = 0.6


def prerequisite_chain(package: SubjectPackage, skill_id: str) -> list[str]:
    """Transitive prerequisites of a skill, topologically ordered, roots first.

    The curriculum validator has already proven the skill graph is acyclic, so a
    plain depth-first post-order is a valid topological order here. The ``seen``
    set still guards against revisiting a shared prerequisite, which is a diamond
    rather than a cycle.
    """
    index = package.curriculum.skill_index()
    order: list[str] = []
    seen: set[str] = set()

    def visit(current: str) -> None:
        skill = index.get(current)
        if skill is None:
            return
        for prereq in skill.prerequisites:
            if prereq in seen:
                continue
            seen.add(prereq)
            visit(prereq)
            order.append(prereq)

    visit(skill_id)
    return order


def blocking_prerequisites(
    package: SubjectPackage,
    skill_id: str,
    masteries: dict[str, SkillMastery],
) -> list[BlockingSkillOut]:
    """Direct prerequisites that are below the threshold.

    Only *direct* prerequisites are reported. If A needs B needs C and both are
    unstarted, the actionable answer is B — telling the learner to go and do C as
    well is technically true and practically noise. C surfaces once B is opened.
    """
    index = package.curriculum.skill_index()
    skill = index.get(skill_id)
    if skill is None:
        return []
    blocking: list[BlockingSkillOut] = []
    for prereq_id in skill.prerequisites:
        prereq = index.get(prereq_id)
        if prereq is None:
            continue
        mastery = masteries.get(prereq_id)
        overall = mastery.overall if mastery else 0.0
        if overall < READINESS_THRESHOLD:
            blocking.append(
                BlockingSkillOut(
                    skill_id=prereq_id,
                    title=prereq.title,
                    mastery=overall,
                    required=READINESS_THRESHOLD,
                )
            )
    return blocking


def readiness_for_skill(
    package: SubjectPackage,
    skill_id: str,
    masteries: dict[str, SkillMastery],
) -> ReadinessOut:
    skill = package.skill(skill_id)
    title = skill.title if skill else skill_id
    mastery = masteries.get(skill_id)
    blocking = blocking_prerequisites(package, skill_id, masteries)
    return ReadinessOut(
        skill_id=skill_id,
        title=title,
        ready=not blocking,
        # ``None`` rather than 0.0 when there is no evidence: the UI renders a dash.
        mastery=mastery.overall if mastery and mastery.evidence_count > 0 else None,
        blocking=blocking,
        chain=prerequisite_chain(package, skill_id),
    )


def is_ready(package: SubjectPackage, skill_id: str, masteries: dict[str, SkillMastery]) -> bool:
    return not blocking_prerequisites(package, skill_id, masteries)


def concept_mastery(concept: Concept, masteries: dict[str, SkillMastery]) -> float | None:
    """A concept's mastery is the mean over the skills it feeds.

    Concepts are not scored directly — nothing is measured by reading. What can be
    said about a concept is how well the learner performs the skills it explains,
    which is why this returns ``None`` when the concept claims no skills at all.
    """
    scored = [masteries[s] for s in concept.skills if s in masteries and masteries[s].evidence_count > 0]
    if not scored:
        return None
    return sum(m.overall for m in scored) / len(scored)


def concept_prerequisite_status(
    package: SubjectPackage,
    concept: Concept,
    masteries: dict[str, SkillMastery] | None,
) -> list[PrerequisiteStatusOut]:
    """Per-prerequisite advice for the lesson header.

    ``masteries is None`` means an anonymous caller. Everything reads ready with a
    null mastery in that case: a public lesson page covered in warnings a visitor
    cannot act on is worse than no warnings.
    """
    statuses: list[PrerequisiteStatusOut] = []
    for prereq_id in concept.prerequisites:
        prereq = package.concepts.get(prereq_id)
        if prereq is None:
            continue
        if masteries is None:
            statuses.append(PrerequisiteStatusOut(concept_id=prereq_id, title=prereq.title, mastery=None, ready=True))
            continue
        mastery = concept_mastery(prereq, masteries)
        statuses.append(
            PrerequisiteStatusOut(
                concept_id=prereq_id,
                title=prereq.title,
                mastery=mastery,
                ready=mastery is not None and mastery >= READINESS_THRESHOLD,
            )
        )
    return statuses
