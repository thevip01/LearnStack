"""Assembling a concept into the payload the lesson view renders.

A concept in a package is authored content. A concept on the wire is authored
content *plus* the learner's position in it: which practice is attached and how it
has gone, what the prerequisites look like right now, and where next and previous
point.

This module is pure. It takes the learner's attempt stats and masteries as
arguments rather than fetching them, which keeps the whole knowledge package free
of any dependency on ``practice``: the two would otherwise import each other,
since the submission pipeline needs readiness. The route owns the session and does
both lookups.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from learnos_schema import Concept, SkillMastery, SubjectPackage

from ...schemas.concept import ConceptOut, ModuleRefOut
from ...schemas.practice import PracticeSummary
from ..subjects.assemble import practice_summary
from ..subjects.registry import LoadedSubject
from .readiness import concept_prerequisite_status

#: ``task_id -> (state, best_score, attempt_count)``, as returned by
#: ``practice.attempts.attempt_stats``.
AttemptStats = Mapping[str, "tuple[str, float | None, int]"]


def module_ref(package: SubjectPackage, concept_id: str) -> ModuleRefOut | None:
    """Which track and module a concept sits in, for the breadcrumb."""
    for track in package.curriculum.tracks:
        for module in track.modules:
            if concept_id in module.concepts:
                return ModuleRefOut(
                    id=module.id,
                    title=module.title,
                    track_id=track.id,
                    track_title=track.title,
                )
    return None


def neighbours(order: Sequence[str], concept_id: str) -> tuple[str | None, str | None]:
    """``(prev, next)`` in curriculum order."""
    try:
        index = list(order).index(concept_id)
    except ValueError:
        return None, None
    prev_id = order[index - 1] if index > 0 else None
    next_id = order[index + 1] if index + 1 < len(order) else None
    return prev_id, next_id


def attached_practice(
    package: SubjectPackage,
    concept: Concept,
    *,
    stats: AttemptStats | None = None,
) -> list[PracticeSummary]:
    """Practice summaries for a concept, in authored order.

    A task listed on the concept but missing from the package is skipped rather
    than raising: validation rejects that state, but a draft package being edited
    live should still render the lesson it does have.
    """
    summaries: list[PracticeSummary] = []
    for task_id in concept.practice:
        task = package.practice.get(task_id)
        if task is None:
            continue
        state, best, count = (stats or {}).get(task_id, ("untouched", None, 0))
        summaries.append(practice_summary(task, state=state, best_score=best, attempts=count))
    return summaries


def concept_out(
    *,
    subject: LoadedSubject,
    concept: Concept,
    stats: AttemptStats | None = None,
    masteries: dict[str, SkillMastery] | None = None,
) -> ConceptOut:
    package = subject.package
    prev_id, next_id = neighbours(subject.concept_order, concept.id)
    return ConceptOut(
        **concept.model_dump(),
        practice=attached_practice(package, concept, stats=stats),
        prerequisite_status=concept_prerequisite_status(package, concept, masteries),
        next_concept_id=next_id,
        prev_concept_id=prev_id,
        module=module_ref(package, concept.id),
    )
