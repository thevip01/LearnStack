"""Catalogue envelope."""

from __future__ import annotations

from learnos_schema import ThemeSpec
from pydantic import Field

from .common import ApiModel


class CatalogProgressOut(ApiModel):
    """The three numbers a subject card needs. Not the full rollup: the catalogue
    lists every subject, and sending each one's per-skill breakdown would make the
    landing page the heaviest request in the product."""

    overall: float
    skills_mastered: int
    skills_total: int


class CatalogSubjectOut(ApiModel):
    id: str
    title: str
    subtitle: str | None = None
    description: str
    provider: str | None = None
    version: str
    status: str
    theme: ThemeSpec
    tags: list[str] = Field(default_factory=list)
    concept_count: int = 0
    practice_count: int = 0
    project_count: int = 0
    estimated_minutes: int = 0
    progress: CatalogProgressOut | None = None


class CatalogDomainOut(ApiModel):
    id: str
    title: str
    icon: str | None = None
    subjects: list[CatalogSubjectOut] = Field(default_factory=list)


class CatalogOut(ApiModel):
    domains: list[CatalogDomainOut] = Field(default_factory=list)
