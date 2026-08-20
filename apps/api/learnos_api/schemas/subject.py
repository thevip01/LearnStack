"""The subject runtime envelope.

``SubjectRuntimeOut`` is the single payload that turns the generic frontend into
this subject. Everything here is precomputed server-side — merged mode layouts,
flattened navigation — because each of those derivations would otherwise be
reimplemented in the web app, and a second implementation is a second set of
subject-specific bugs.
"""

from __future__ import annotations

from learnos_schema import LearningMode, ModeLayout, NavigationItem, RuntimeSpec, Skill, ThemeSpec, Track
from pydantic import Field

from .common import ApiModel
from .progress import SubjectProgressOut


class DomainOut(ApiModel):
    id: str
    title: str
    icon: str | None = None


class SubjectRuntimeOut(ApiModel):
    id: str
    title: str
    subtitle: str | None = None
    description: str
    domain: DomainOut
    provider: str | None = None
    version: str
    content_hash: str
    status: str
    theme: ThemeSpec
    layout: str
    default_mode: LearningMode
    modes: list[LearningMode] = Field(default_factory=list)
    #: Already merged with ``ui.global_panels``. The frontend renders
    #: ``mode_layouts[mode].panels`` directly and never learns that
    #: ``global_panels`` exists.
    mode_layouts: dict[LearningMode, ModeLayout] = Field(default_factory=dict)
    #: Flattened, ordered, depth-tagged. Sidebar, breadcrumbs and next/prev all
    #: read this one list.
    navigation: list[NavigationItem] = Field(default_factory=list)
    #: Grouping headers only; module concept ids are present but no concept bodies.
    tracks: list[Track] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    runtimes: list[RuntimeSpec] = Field(default_factory=list)
    #: ``null`` for an anonymous caller. The catalogue and lesson content stay
    #: publicly renderable, which is what keeps the subject browsable without a
    #: signup wall.
    progress: SubjectProgressOut | None = None
