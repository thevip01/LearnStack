"""Assembling a package into the payloads the HTTP surface serves.

Everything in here is pure: package in, response model out, no database and no
cache. That is what lets the registry build a subject's runtime payload once at
startup and hand out the same object to every request.
"""

from __future__ import annotations

from typing import Any

from learnos_schema import (
    LearningMode,
    ModeLayout,
    NavigationItem,
    PracticeTask,
    SubjectPackage,
)

from ...schemas.catalog import CatalogSubjectOut
from ...schemas.practice import PracticeSummary
from ...schemas.subject import DomainOut, SubjectRuntimeOut


def enum_value(value: Any) -> Any:
    """Normalise an enum-or-string to its string value.

    ``learnos_schema.SchemaModel`` sets ``use_enum_values=True``, so a field typed
    as an enum holds a plain string once validated — but a value constructed in
    Python before validation is still an enum member. Both shapes reach this layer,
    and dict keys have to be comparable, so everything is normalised on the way out.
    """
    return getattr(value, "value", value)


def mode_layouts(package: SubjectPackage) -> dict[str, ModeLayout]:
    """Pre-merge ``global_panels`` into every mode.

    The frontend renders ``mode_layouts[mode].panels`` and never learns that
    ``global_panels`` exists; doing the merge here means the tutor panel is added
    to a new subject by the schema, not by a frontend change.
    """
    layouts: dict[str, ModeLayout] = {}
    for mode in package.manifest.modes:
        key = enum_value(mode)
        if key in {enum_value(m) for m in package.ui.modes}:
            layouts[key] = package.ui.layout_for(mode)  # type: ignore[arg-type]
    return layouts


def navigation(package: SubjectPackage) -> list[NavigationItem]:
    return package.navigation()


def concept_order(package: SubjectPackage) -> list[str]:
    """Curriculum order of concept ids, used for next/prev links.

    Taken from the flattened navigation rather than from ``curriculum.concept_ids()``
    so that a concept referenced by a module but missing from the package (which
    validation rejects, but drafts hit) cannot produce a dangling next link.
    """
    return [item.id for item in package.navigation() if enum_value(item.kind) == "concept"]


def subject_runtime(package: SubjectPackage, content_hash: str) -> SubjectRuntimeOut:
    manifest = package.manifest
    return SubjectRuntimeOut(
        id=manifest.id,
        title=manifest.title,
        subtitle=manifest.subtitle,
        description=manifest.description,
        domain=DomainOut(id=manifest.domain.id, title=manifest.domain.title, icon=manifest.domain.icon),
        provider=manifest.provider,
        version=manifest.version,
        content_hash=content_hash,
        status=enum_value(manifest.status),
        theme=package.ui.theme,
        layout=enum_value(package.ui.layout),
        default_mode=enum_value(package.ui.default_mode),
        modes=[enum_value(m) for m in manifest.modes],
        mode_layouts=mode_layouts(package),  # type: ignore[arg-type]
        navigation=navigation(package),
        tracks=package.curriculum.tracks,
        skills=package.curriculum.skills,
        runtimes=manifest.runtimes,
        progress=None,
    )


def estimated_minutes(package: SubjectPackage) -> int:
    """Total time-on-task for the catalogue card.

    Concepts and practice contribute their own estimates; projects contribute
    hours. Assessments are excluded because their time limit is a cap, not an
    expectation.
    """
    total = sum(c.estimated_minutes for c in package.concepts.values())
    total += sum(t.estimated_minutes for t in package.practice.values())
    total += int(sum(p.estimated_hours for p in package.projects.values()) * 60)
    return total


def catalog_subject(package: SubjectPackage) -> CatalogSubjectOut:
    manifest = package.manifest
    return CatalogSubjectOut(
        id=manifest.id,
        title=manifest.title,
        subtitle=manifest.subtitle,
        description=manifest.description,
        provider=manifest.provider,
        version=manifest.version,
        status=enum_value(manifest.status),
        theme=package.ui.theme,
        tags=list(manifest.tags),
        concept_count=len(package.concepts),
        practice_count=len(package.practice),
        project_count=len(package.projects),
        estimated_minutes=estimated_minutes(package),
        progress=None,
    )


def practice_summary(
    task: PracticeTask,
    *,
    state: str = "untouched",
    best_score: float | None = None,
    attempts: int = 0,
) -> PracticeSummary:
    """The list-view shape of a task.

    Note what is *not* here: no prompt, no questions, no files. A summary is safe
    to return in bulk precisely because it carries nothing a grader depends on.
    """
    return PracticeSummary(
        id=task.id,
        kind=enum_value(task.kind),
        title=task.title,
        difficulty=task.difficulty,
        estimated_minutes=task.estimated_minutes,
        hint_count=len(task.hints),
        skills=list(task.skills),
        state=state,  # type: ignore[arg-type]
        best_score=best_score,
        attempts=attempts,
    )


def all_modes(package: SubjectPackage) -> list[LearningMode]:
    return [enum_value(m) for m in package.manifest.modes]
