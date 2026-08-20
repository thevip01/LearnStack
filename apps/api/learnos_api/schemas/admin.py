"""Admin and ingestion envelopes.

The ingestion shapes are ``learnos_schema.ingestion`` models passed straight
through. The admin API is a thin projection over the pipeline's tables, not a
second model of them: the pipeline owns the semantics, this owns the HTTP.
"""

from __future__ import annotations

from typing import Any, Literal

from learnos_schema import Provenance, SourceRef
from pydantic import BaseModel, Field

from .common import ApiModel

ReviewDecision = Literal["approve", "reject", "request_changes"]


class SubjectLoadFailureOut(ApiModel):
    id: str
    problems: list[str] = Field(default_factory=list)


class SubjectReloadOut(ApiModel):
    loaded: list[str] = Field(default_factory=list)
    failed: list[SubjectLoadFailureOut] = Field(default_factory=list)


class SubjectValidateOut(ApiModel):
    problems: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceListOut(ApiModel):
    sources: list[dict[str, Any]] = Field(default_factory=list)


class RunListOut(ApiModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)


class CandidateListOut(ApiModel):
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class RunCreateIn(BaseModel):
    subject_id: str
    source_ids: list[str] | None = None
    stages: list[str] | None = None
    #: Defaults to a dry run. An ingestion run that writes by default is how a
    #: package gets clobbered by a mistyped curl.
    dry_run: bool = True


class CandidateReviewIn(BaseModel):
    decision: ReviewDecision
    notes: str | None = Field(default=None, max_length=4_000)
    #: An edited payload the reviewer wants stored in place of the extractor's.
    payload: dict[str, Any] | None = None


class ProvenanceChainStepOut(ApiModel):
    stage: str
    id: str
    label: str
    detail: str | None = None


class ProvenanceTrailOut(ApiModel):
    entity_id: str
    entity_kind: str
    provenance: Provenance
    sources: list[SourceRef] = Field(default_factory=list)
    #: source -> document -> chunk -> candidate -> published entity, in that order.
    chain: list[ProvenanceChainStepOut] = Field(default_factory=list)
