"""Mastery: evidence in, scores out.

The rule this module exists to enforce: a score is never set, it is *derived*
from evidence rows. "Lesson viewed" is not evidence. A passing submission with
three hints burned is weaker evidence than a passing submission with none, and
week-old evidence is weaker than today's.

Keeping the maths here, in the shared package, means the API, the recommender and
the ingestion-time difficulty calibration all agree on what 74% means.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

from pydantic import Field

from .common import Id, MasteryDimension, SchemaModel, Score, utcnow

# Default mix. Subjects and individual skills may override.
DEFAULT_DIMENSION_WEIGHTS: dict[MasteryDimension, float] = {
    MasteryDimension.CONCEPT: 0.20,
    MasteryDimension.PRACTICE: 0.25,
    MasteryDimension.LAB: 0.20,
    MasteryDimension.DEBUGGING: 0.15,
    MasteryDimension.PRODUCTION: 0.10,
    MasteryDimension.RETENTION: 0.10,
}

# How much a single hint costs on the practice dimension, and the floor.
HINT_PENALTY_PER_LEVEL = 0.15
HINT_PENALTY_FLOOR = 0.40

# Evidence half-life. Old passes decay toward, but never to, zero.
EVIDENCE_HALF_LIFE_DAYS = 90.0
RECENCY_FLOOR = 0.35

MASTERY_THRESHOLD = 0.75
AT_RISK_THRESHOLD = 0.50


class Evidence(SchemaModel):
    """One observation about one skill on one dimension."""

    skill_id: Id
    dimension: MasteryDimension
    score: Score
    weight: float = Field(default=1.0, gt=0.0, description="Task difficulty and coverage. Harder tasks count more.")
    source_type: str = Field(description="'practice', 'assessment', 'project', 'incident', 'review'.")
    source_id: Id | None = None
    hints_used: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utcnow)

    def effective_score(self) -> float:
        return apply_hint_penalty(self.score, self.hints_used, self.dimension)

    def recency_factor(self, now: datetime | None = None) -> float:
        now = now or utcnow()
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=now.tzinfo)
        age_days = max((now - created).total_seconds() / 86400.0, 0.0)
        decay = 0.5 ** (age_days / EVIDENCE_HALF_LIFE_DAYS)
        return RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * decay


def apply_hint_penalty(score: float, hints_used: int, dimension: MasteryDimension | str) -> float:
    """Hints are free on the concept dimension and costly on the doing dimensions.

    Reading an explanation while learning a definition is fine. Being walked
    through a debugging session is not evidence you can debug.

    ``dimension`` is typed loosely because that is the truth: every caller that
    reaches here through an ``Evidence`` row passes a ``str``. Compared by value for
    the reason spelled out on ``SchemaModel``.
    """
    if hints_used <= 0 or dimension == MasteryDimension.CONCEPT:
        return score
    factor = max(HINT_PENALTY_FLOOR, 1.0 - HINT_PENALTY_PER_LEVEL * hints_used)
    return score * factor


class DimensionScore(SchemaModel):
    dimension: MasteryDimension
    score: Score = 0.0
    evidence_count: int = 0
    last_evidence_at: datetime | None = None
    measured: bool = Field(default=False, description="False means no evidence exists yet; do not render 0%.")


class SkillMastery(SchemaModel):
    skill_id: Id
    overall: Score = 0.0
    dimensions: dict[MasteryDimension, DimensionScore] = Field(default_factory=dict)
    coverage: Score = Field(default=0.0, description="Share of the weighted dimensions that have any evidence at all.")
    evidence_count: int = 0
    last_practiced_at: datetime | None = None

    @property
    def state(self) -> str:
        if self.evidence_count == 0:
            return "untouched"
        if self.coverage < 0.5:
            return "partially_measured"
        if self.overall >= MASTERY_THRESHOLD:
            return "mastered"
        if self.overall < AT_RISK_THRESHOLD:
            return "at_risk"
        return "developing"

    @property
    def is_mastered(self) -> bool:
        return self.state == "mastered"


def compute_dimension_score(evidence: Iterable[Evidence], now: datetime | None = None) -> DimensionScore | None:
    """Recency- and difficulty-weighted mean of a dimension's evidence."""
    items = list(evidence)
    if not items:
        return None
    now = now or utcnow()
    numerator = 0.0
    denominator = 0.0
    for item in items:
        weight = item.weight * item.recency_factor(now)
        numerator += item.effective_score() * weight
        denominator += weight
    score = numerator / denominator if denominator else 0.0
    return DimensionScore(
        dimension=items[0].dimension,
        score=min(max(score, 0.0), 1.0),
        evidence_count=len(items),
        last_evidence_at=max(i.created_at for i in items),
        measured=True,
    )


def compute_skill_mastery(
    skill_id: str,
    evidence: Iterable[Evidence],
    weights: dict[MasteryDimension, float] | None = None,
    now: datetime | None = None,
) -> SkillMastery:
    """Roll evidence up into one skill's mastery record.

    Unmeasured dimensions are excluded from the denominator rather than scored
    zero, and ``coverage`` reports how much of the picture is missing. A learner
    who has done the reading and none of the labs should see "70% on 45% of the
    evidence", not a flat 31% that looks like failure.
    """
    weights = weights or DEFAULT_DIMENSION_WEIGHTS
    now = now or utcnow()
    by_dimension: dict[MasteryDimension, list[Evidence]] = {}
    for item in evidence:
        by_dimension.setdefault(item.dimension, []).append(item)

    dimensions: dict[MasteryDimension, DimensionScore] = {}
    for dimension in weights:
        computed = compute_dimension_score(by_dimension.get(dimension, []), now)
        dimensions[dimension] = computed or DimensionScore(dimension=dimension, measured=False)

    measured_weight = sum(w for d, w in weights.items() if dimensions[d].measured)
    total_weight = sum(weights.values()) or 1.0
    overall = 0.0
    if measured_weight > 0:
        overall = sum(
            dimensions[d].score * w for d, w in weights.items() if dimensions[d].measured
        ) / measured_weight

    all_evidence = [e for items in by_dimension.values() for e in items]
    return SkillMastery(
        skill_id=skill_id,
        overall=min(max(overall, 0.0), 1.0),
        dimensions=dimensions,
        coverage=measured_weight / total_weight,
        evidence_count=len(all_evidence),
        last_practiced_at=max((e.created_at for e in all_evidence), default=None),
    )


# ---------------------------------------------------------------------------
# Adaptive difficulty
# ---------------------------------------------------------------------------

ABILITY_LEARNING_RATE = 0.8
ABILITY_MIN, ABILITY_MAX = 1.0, 10.0


def update_ability(ability: float, difficulty: int, score: float) -> float:
    """Elo-flavoured ability update on the 1-10 difficulty scale.

    Expected performance falls off with the gap between ability and difficulty.
    Beating a task well above your level moves you a lot; scraping a pass on an
    easy one barely moves you at all.
    """
    expected = 1.0 / (1.0 + math.exp((difficulty - ability) / 1.5))
    updated = ability + ABILITY_LEARNING_RATE * (score - expected)
    return min(max(updated, ABILITY_MIN), ABILITY_MAX)


def target_difficulty(ability: float, consecutive_failures: int = 0) -> int:
    """Aim slightly above current ability, and back off hard after failures.

    Two failures in a row means the learner is not merely being stretched, they
    are missing something upstream. Dropping below their ability lets them
    re-establish footing before the recommender sends them to a prerequisite.
    """
    target = ability + 0.5
    if consecutive_failures >= 2:
        target = ability - 1.5
    elif consecutive_failures == 1:
        target = ability - 0.5
    return int(min(max(round(target), 1), 10))
