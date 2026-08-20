"""Graph, readiness and recommendation envelopes."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiModel

NodeKind = Literal["concept", "skill"]
EdgeKind = Literal["prerequisite", "composes", "analogue", "evidences"]
RecommendationKind = Literal["concept", "practice", "project", "assessment", "review"]


class GraphNodeOut(ApiModel):
    id: str
    kind: NodeKind
    label: str
    category: str | None = None
    difficulty: int | None = None
    skills: list[str] | None = None
    #: ``null`` means unmeasured, which the UI draws differently from 0.
    mastery: float | None = None


class GraphEdgeOut(ApiModel):
    source: str
    target: str
    kind: EdgeKind


class GraphOut(ApiModel):
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)


class BlockingSkillOut(ApiModel):
    skill_id: str
    title: str
    mastery: float
    required: float


class ReadinessOut(ApiModel):
    skill_id: str
    title: str
    ready: bool
    mastery: float | None = None
    blocking: list[BlockingSkillOut] = Field(default_factory=list)
    #: Topologically ordered transitive prerequisites, roots first.
    chain: list[str] = Field(default_factory=list)


class RecommendationOut(ApiModel):
    kind: RecommendationKind
    id: str
    title: str
    #: A short human sentence, displayed verbatim. The frontend is contractually
    #: forbidden from composing one, so an empty string here is a bug.
    reason: str
    score: float
    skill_id: str | None = None
    target_difficulty: int | None = None


class RecommendationsOut(ApiModel):
    subject_id: str
    recommendations: list[RecommendationOut] = Field(default_factory=list)
