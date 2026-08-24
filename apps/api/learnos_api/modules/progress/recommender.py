"""The recommender: what to do next, and why.

This is the module that makes the platform feel adaptive, and it is also the one
most able to feel arbitrary if it is careless. Three rules keep it honest:

* **Every recommendation carries a sentence composed here.** The contract forbids
  the frontend from writing that sentence, because a reason assembled from a score
  in the client drifts from the reason the server actually had. An empty ``reason``
  is a bug, not a default.
* **Prerequisites come before difficulty.** If a skill's prerequisite is weak, the
  right recommendation is the prerequisite, not a harder task in the skill the
  learner is currently failing.
* **Difficulty backs off after repeated failure.** Two consecutive failures means
  something upstream is missing; ``target_difficulty`` drops so the next task is
  winnable. Handing someone a third attempt at the same wall is how learners
  conclude they are the problem.

Nothing here writes. It reads mastery, skill state and attempt history, all passed
in by the caller, and returns ranked candidates. That means it can be unit-tested
over fixtures with no database, and it keeps this module free of any import from
``practice`` (which imports the pipeline, which imports readiness: the cycle this
avoids).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from learnos_schema import (
    MASTERY_THRESHOLD,
    PracticeTask,
    SkillMastery,
    SubjectPackage,
    target_difficulty,
)

from ...schemas.graph import RecommendationOut, RecommendationsOut
from ...schemas.practice import NextUpOut
from ..knowledge.readiness import READINESS_THRESHOLD, blocking_prerequisites
from ..subjects.assemble import enum_value

#: How long before practised-and-passed work is worth revisiting. Shorter than the
#: 90-day evidence half-life on purpose: the point of review is to catch decay
#: before it shows up as a dropped score.
REVIEW_AFTER_DAYS = 21

#: Score floors so that the ranking is stable and explainable rather than a pile of
#: tuned magic numbers. Higher wins.
SCORE_BLOCKED_PREREQUISITE = 0.95
SCORE_UNREAD_CONCEPT = 0.80
SCORE_WEAK_SKILL_PRACTICE = 0.70
SCORE_NEXT_IN_ORDER = 0.55
SCORE_REVIEW = 0.45
SCORE_PROJECT = 0.40
SCORE_ASSESSMENT = 0.35


@dataclass(frozen=True)
class LearnerView:
    """Everything the recommender is allowed to know about a learner.

    A single struct rather than eight keyword arguments because every caller
    assembles all of it anyway, and because a new signal should be added in one
    place.
    """

    masteries: Mapping[str, SkillMastery]
    ability: Mapping[str, float]
    consecutive_failures: Mapping[str, int]
    last_practiced: Mapping[str, datetime | None]
    passed_task_ids: frozenset[str]
    viewed_concept_ids: frozenset[str]

    @classmethod
    def empty(cls) -> "LearnerView":
        return cls({}, {}, {}, {}, frozenset(), frozenset())

    def ability_for(self, skill_id: str) -> float:
        return float(self.ability.get(skill_id, 3.0))

    def failures_for(self, skill_id: str) -> int:
        return int(self.consecutive_failures.get(skill_id, 0))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------


def _tasks_for_skill(package: SubjectPackage, skill_id: str) -> list[PracticeTask]:
    return [task for task in package.practice.values() if skill_id in task.skills]


def _best_task(
    tasks: Sequence[PracticeTask],
    *,
    wanted_difficulty: int,
    exclude: Iterable[str],
) -> PracticeTask | None:
    """The unsolved task closest to the target difficulty.

    Ties break toward the easier task. When the estimate is uncertain, and after
    a failure it always is, the cheaper mistake is a task that is slightly too
    easy.
    """
    blocked = set(exclude)
    available = [task for task in tasks if task.id not in blocked]
    if not available:
        return None
    return min(available, key=lambda task: (abs(task.difficulty - wanted_difficulty), task.difficulty))


def _weak_skills(package: SubjectPackage, view: LearnerView) -> list[tuple[str, SkillMastery | None]]:
    """Skills with evidence that are below mastery, weakest first."""
    scored: list[tuple[float, str, SkillMastery]] = []
    for skill in package.curriculum.skills:
        mastery = view.masteries.get(skill.id)
        if mastery is None or mastery.evidence_count == 0:
            continue
        if mastery.overall < MASTERY_THRESHOLD:
            scored.append((mastery.overall, skill.id, mastery))
    scored.sort(key=lambda item: item[0])
    return [(skill_id, mastery) for _, skill_id, mastery in scored]


def _unstarted_concepts(package: SubjectPackage, order: Sequence[str], view: LearnerView) -> list[str]:
    return [concept_id for concept_id in order if concept_id not in view.viewed_concept_ids]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _prerequisite_recommendations(
    package: SubjectPackage,
    view: LearnerView,
    *,
    limit: int,
) -> list[RecommendationOut]:
    """Point at the weak prerequisite behind whatever the learner is struggling with."""
    out: list[RecommendationOut] = []
    index = package.curriculum.skill_index()
    for skill_id, mastery in _weak_skills(package, view):
        for blocking in blocking_prerequisites(package, skill_id, dict(view.masteries)):
            concept_id = next(
                (c.id for c in package.concepts.values() if blocking.skill_id in c.skills),
                None,
            )
            skill = index.get(skill_id)
            downstream = skill.title if skill else skill_id
            if concept_id is not None:
                out.append(
                    RecommendationOut(
                        kind="concept",
                        id=concept_id,
                        title=package.concepts[concept_id].title,
                        reason=(
                            f"{blocking.title} is at {_pct(blocking.mastery)} and "
                            f"{downstream} builds directly on it. Shoring this up first is "
                            "usually faster than pushing harder on the thing that is failing."
                        ),
                        score=SCORE_BLOCKED_PREREQUISITE,
                        skill_id=blocking.skill_id,
                    )
                )
            if len(out) >= limit:
                return out
    return out


def _practice_recommendations(
    package: SubjectPackage,
    view: LearnerView,
    *,
    limit: int,
) -> list[RecommendationOut]:
    """A task at the right difficulty in the learner's weakest measured skill."""
    out: list[RecommendationOut] = []
    index = package.curriculum.skill_index()
    for skill_id, mastery in _weak_skills(package, view):
        failures = view.failures_for(skill_id)
        wanted = target_difficulty(view.ability_for(skill_id), failures)
        task = _best_task(_tasks_for_skill(package, skill_id), wanted_difficulty=wanted, exclude=view.passed_task_ids)
        if task is None:
            continue
        skill = index.get(skill_id)
        title = skill.title if skill else skill_id
        if failures >= 2:
            reason = (
                f"Two attempts at {title} have not landed, so this one is easier "
                f"(difficulty {task.difficulty}). Getting a clean pass here is worth more "
                "than another try at the harder one."
            )
        elif mastery and mastery.coverage < 0.5:
            reason = (
                f"{title} is only partly measured: this is a "
                f"{enum_value(task.kind)} task, which fills in a dimension nothing has tested yet."
            )
        else:
            reason = (
                f"{title} sits at {_pct(mastery.overall if mastery else 0.0)}. "
                f"This task is pitched at difficulty {task.difficulty}, just above where you are now."
            )
        out.append(
            RecommendationOut(
                kind="practice",
                id=task.id,
                title=task.title,
                reason=reason,
                score=SCORE_WEAK_SKILL_PRACTICE,
                skill_id=skill_id,
                target_difficulty=wanted,
            )
        )
        if len(out) >= limit:
            break
    return out


def _concept_recommendations(
    package: SubjectPackage,
    order: Sequence[str],
    view: LearnerView,
    *,
    limit: int,
) -> list[RecommendationOut]:
    out: list[RecommendationOut] = []
    for concept_id in _unstarted_concepts(package, order, view)[:limit]:
        concept = package.concepts.get(concept_id)
        if concept is None:
            continue
        blocking = [
            item
            for skill_id in concept.skills
            for item in blocking_prerequisites(package, skill_id, dict(view.masteries))
        ]
        if blocking:
            reason = (
                f"Next in the curriculum, though {blocking[0].title} is still at "
                f"{_pct(blocking[0].mastery)}, worth a look first, but nothing is stopping you."
            )
            score = SCORE_NEXT_IN_ORDER
        else:
            reason = "Next in the curriculum, and everything it depends on is already in place."
            score = SCORE_UNREAD_CONCEPT
        out.append(
            RecommendationOut(
                kind="concept",
                id=concept_id,
                title=concept.title,
                reason=reason,
                score=score,
            )
        )
    return out


def _review_recommendations(
    package: SubjectPackage,
    view: LearnerView,
    *,
    limit: int,
) -> list[RecommendationOut]:
    """Passed work that has gone quiet long enough to be worth revisiting."""
    cutoff = _now() - timedelta(days=REVIEW_AFTER_DAYS)
    index = package.curriculum.skill_index()
    out: list[RecommendationOut] = []
    for skill in package.curriculum.skills:
        mastery = view.masteries.get(skill.id)
        if mastery is None or mastery.evidence_count == 0 or mastery.overall < MASTERY_THRESHOLD:
            continue
        last = view.last_practiced.get(skill.id) or mastery.last_practiced_at
        if last is None:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last > cutoff:
            continue
        task = _best_task(
            _tasks_for_skill(package, skill.id),
            wanted_difficulty=target_difficulty(view.ability_for(skill.id), 0),
            exclude=(),  # a review deliberately reuses something already passed
        )
        if task is None:
            continue
        days = max((_now() - last).days, REVIEW_AFTER_DAYS)
        title = (index.get(skill.id).title if index.get(skill.id) else skill.id)
        out.append(
            RecommendationOut(
                kind="review",
                id=task.id,
                title=task.title,
                reason=(
                    f"You passed {title} {days} days ago and have not touched it since. "
                    "A quick re-run is how retention gets measured rather than assumed."
                ),
                score=SCORE_REVIEW,
                skill_id=skill.id,
            )
        )
        if len(out) >= limit:
            break
    return out


def _milestone_recommendations(
    package: SubjectPackage,
    view: LearnerView,
    *,
    limit: int,
) -> list[RecommendationOut]:
    """A project or assessment, once enough of the subject is actually solid."""
    out: list[RecommendationOut] = []
    for project in package.projects.values():
        required = list(getattr(project, "skills", []) or [])
        if not required:
            continue
        ready = [
            skill_id
            for skill_id in required
            if (view.masteries.get(skill_id).overall if view.masteries.get(skill_id) else 0.0) >= READINESS_THRESHOLD
        ]
        if len(ready) < max(1, len(required) - 1):
            continue
        out.append(
            RecommendationOut(
                kind="project",
                id=project.id,
                title=project.title,
                reason=(
                    f"{len(ready)} of the {len(required)} skills this project needs are above "
                    f"{_pct(READINESS_THRESHOLD)}. Building something end to end is the part that "
                    "makes the pieces stick together."
                ),
                score=SCORE_PROJECT,
            )
        )
        if len(out) >= limit:
            return out

    for assessment in package.assessments.values():
        out.append(
            RecommendationOut(
                kind="assessment",
                id=assessment.id,
                title=assessment.title,
                reason=(
                    "This checks several skills at once under a time limit, which is a "
                    "different thing from passing them one at a time."
                ),
                score=SCORE_ASSESSMENT,
            )
        )
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def recommend(
    package: SubjectPackage,
    *,
    concept_order: Sequence[str],
    view: LearnerView,
    limit: int = 6,
) -> RecommendationsOut:
    """Ranked next actions for one learner in one subject.

    Rules run in priority order and each contributes at most a couple of
    candidates, so a learner with one very weak skill still gets a varied list
    instead of six variations on the same task.
    """
    limit = min(max(limit, 1), 20)
    candidates: list[RecommendationOut] = []
    candidates += _prerequisite_recommendations(package, view, limit=2)
    candidates += _practice_recommendations(package, view, limit=3)
    candidates += _concept_recommendations(package, concept_order, view, limit=2)
    candidates += _review_recommendations(package, view, limit=2)
    candidates += _milestone_recommendations(package, view, limit=1)

    seen: set[tuple[str, str]] = set()
    unique: list[RecommendationOut] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        key = (candidate.kind, candidate.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    if not unique:
        # A brand new learner with no evidence and no viewed concepts still needs a
        # front door, and "nothing to suggest" is never the right answer.
        first = concept_order[0] if concept_order else None
        if first and first in package.concepts:
            unique.append(
                RecommendationOut(
                    kind="concept",
                    id=first,
                    title=package.concepts[first].title,
                    reason="Start here: it is the first concept in this subject and nothing precedes it.",
                    score=SCORE_UNREAD_CONCEPT,
                )
            )

    return RecommendationsOut(subject_id=package.manifest.id, recommendations=unique[:limit])


def next_up(
    package: SubjectPackage,
    *,
    concept_order: Sequence[str],
    view: LearnerView,
    exclude_task_id: str | None = None,
) -> NextUpOut | None:
    """The single suggestion shown after a submission.

    Excludes the task just submitted: "try that again" is what the retry button is
    for, and offering it as a recommendation reads as the platform not noticing
    what the learner just did.
    """
    result = recommend(package, concept_order=concept_order, view=view, limit=6)
    for candidate in result.recommendations:
        if exclude_task_id and candidate.id == exclude_task_id:
            continue
        return NextUpOut(kind=candidate.kind, id=candidate.id, title=candidate.title, reason=candidate.reason)
    return None
