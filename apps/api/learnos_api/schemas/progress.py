"""Progress envelopes.

The ``measured`` flag on every dimension is the whole point of this shape. An
unmeasured dimension is not a zero, and the contract requires the UI to render it
as a dash; sending ``{"score": 0.0, "measured": false}`` keeps that distinction on
the wire instead of asking the client to infer it.
"""

from __future__ import annotations

from learnos_schema import MasteryDimension
from pydantic import Field

from .common import ApiModel, UtcDatetime
from .graph import ReadinessOut
from .practice import PracticeSummary, SkillState


class DimensionOut(ApiModel):
    score: float = 0.0
    measured: bool = False


class ProgressSummaryOut(ApiModel):
    overall: float = 0.0
    coverage: float = 0.0
    skills_total: int = 0
    skills_mastered: int = 0
    skills_at_risk: int = 0
    concepts_seen: int = 0
    practice_passed: int = 0
    projects_completed: int = 0
    minutes_practised: float = 0.0
    streak_days: int = 0


class SkillProgressOut(ApiModel):
    skill_id: str
    title: str
    overall: float
    coverage: float
    state: SkillState
    ability: float
    dimensions: dict[MasteryDimension, DimensionOut] = Field(default_factory=dict)
    last_practiced_at: UtcDatetime | None = None


class SubjectProgressOut(ApiModel):
    subject_id: str
    summary: ProgressSummaryOut = Field(default_factory=ProgressSummaryOut)
    dimensions: dict[MasteryDimension, DimensionOut] = Field(default_factory=dict)
    skills: list[SkillProgressOut] = Field(default_factory=list)


class EvidenceOut(ApiModel):
    dimension: MasteryDimension
    score: float
    weight: float
    source_type: str
    source_id: str | None = None
    hints_used: int
    created_at: UtcDatetime
    #: Recomputed on read from ``created_at``, so an old row's contribution is
    #: visible in the UI without the client knowing the half-life.
    recency_factor: float


class SkillDetailOut(ApiModel):
    #: The authored ``learnos_schema.Skill``, passed through untouched.
    skill: dict
    mastery: SkillProgressOut
    evidence: list[EvidenceOut] = Field(default_factory=list)
    readiness: ReadinessOut
    recommended_practice: list[PracticeSummary] = Field(default_factory=list)


class HistoryPointOut(ApiModel):
    date: str
    overall: float
    skills_mastered: int
    #: The same six axes as ``SubjectProgressOut.dimensions``, recomputed at this
    #: day's cutoff. Carries ``measured`` for the usual reason: a day before a
    #: learner ever ran a lab has no lab score, which is not the same as a zero and
    #: must not be drawn as a point on the floor.
    dimensions: dict[MasteryDimension, DimensionOut] = Field(default_factory=dict)


class HistoryOut(ApiModel):
    points: list[HistoryPointOut] = Field(default_factory=list)
