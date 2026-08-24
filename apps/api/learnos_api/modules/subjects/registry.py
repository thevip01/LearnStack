"""The subject registry: load once, serve many.

Filesystem reads happen exactly twice in this service's life: at startup and on
``POST /admin/subjects/reload``. Every request is served from the in-memory
dictionary this class holds. That is the requirement that makes the "generic
subject runtime" thesis affordable: a subject package is megabytes of JSON with
thousands of cross-references, and re-reading it per request would make the
cheapest endpoint the most expensive one.

Two failure rules matter:

* A package that fails validation **must not** break startup. Its problems are
  logged, recorded in ``subject_versions`` with ``load_ok=false``, and reported by
  ``/admin/subjects/reload``. One malformed subject cannot take the platform down.
* A reload is atomic from a reader's point of view. The new dictionaries are built
  off to the side and swapped in, so no request ever sees a half-loaded registry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from learnos_schema import (
    Assessment,
    PracticeTask,
    Project,
    RuntimeSpec,
    Skill,
    SubjectPackage,
    discover_packages,
    load_subject_package,
)
from learnos_schema.package import PackageValidationError
from pydantic import ValidationError

from ... import cache
from ...errors import NotFound
from ...logging import get_logger
from ...schemas.subject import SubjectRuntimeOut
from . import assemble

log = get_logger(__name__)

#: Platform default runner images, used for ad-hoc runs and for any subject that
#: does not declare a runtime of its own. Pinned: an unpinned runner image means a
#: task that passed yesterday can fail today for reasons no learner can debug.
DEFAULT_RUNTIME_IMAGES: dict[str, RuntimeSpec] = {
    "python": RuntimeSpec(
        id="python-3.12",
        kind="python",  # type: ignore[arg-type]
        version="3.12",
        image="learnos/runner-python:3.12",
        default_command="python main.py",
        packages=["pytest", "pytest-json-report"],
        supports_tests=True,
    ),
}


@dataclass
class LoadFailure:
    subject_id: str
    path: str
    problems: list[str]


@dataclass
class LoadedSubject:
    package: SubjectPackage
    content_hash: str
    path: Path
    loaded_at: datetime
    runtime: SubjectRuntimeOut
    #: Curriculum order of concept ids, precomputed for next/prev links.
    concept_order: list[str] = field(default_factory=list)
    #: concept_id -> (module_id, module_title, track_id, track_title)
    concept_module: dict[str, tuple[str, str, str, str]] = field(default_factory=dict)


@dataclass
class LoadReport:
    loaded: list[str] = field(default_factory=list)
    failed: list[LoadFailure] = field(default_factory=list)


class SubjectRegistry:
    """In-memory home for every loaded subject package."""

    def __init__(self, subjects_dir: Path) -> None:
        self.subjects_dir = subjects_dir
        self._subjects: dict[str, LoadedSubject] = {}
        self._task_owner: dict[str, str] = {}
        self._failures: list[LoadFailure] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def reload(self) -> LoadReport:
        """Re-read every package from disk and swap the result in atomically."""
        async with self._lock:
            report = LoadReport()
            subjects: dict[str, LoadedSubject] = {}
            task_owner: dict[str, str] = {}

            directories = await asyncio.to_thread(discover_packages, self.subjects_dir)
            if not directories:
                log.warning("no_subject_packages_found", subjects_dir=str(self.subjects_dir))

            for directory in directories:
                loaded, failure = await asyncio.to_thread(self._load_one, directory)
                if failure is not None:
                    report.failed.append(failure)
                    log.error(
                        "subject_package_rejected",
                        subject_id=failure.subject_id,
                        path=failure.path,
                        problem_count=len(failure.problems),
                        problems=failure.problems[:10],
                    )
                    continue
                assert loaded is not None
                if loaded.package.id in subjects:
                    report.failed.append(
                        LoadFailure(
                            subject_id=loaded.package.id,
                            path=str(directory),
                            problems=[f"duplicate subject id, already loaded from {subjects[loaded.package.id].path}"],
                        )
                    )
                    continue
                subjects[loaded.package.id] = loaded
                report.loaded.append(loaded.package.id)
                for task_id in loaded.package.practice:
                    task_owner[task_id] = loaded.package.id

            self._subjects = subjects
            self._task_owner = task_owner
            self._failures = report.failed
            log.info("subjects_loaded", loaded=report.loaded, failed=[f.subject_id for f in report.failed])
            return report

    def _load_one(self, directory: Path) -> tuple[LoadedSubject | None, LoadFailure | None]:
        """Blocking load of one package. Runs in a worker thread.

        Every exception is caught. A package that raises something unexpected is
        still just one bad package, and the alternative is a service that will not
        boot because somebody committed a broken JSON file.
        """
        try:
            package = load_subject_package(directory)
        except PackageValidationError as exc:
            return None, LoadFailure(exc.subject_id, str(directory), list(exc.problems))
        except ValidationError as exc:
            problems = [
                "{}: {}".format(".".join(str(part) for part in err["loc"]), err["msg"]) for err in exc.errors()
            ]
            return None, LoadFailure(directory.name, str(directory), problems)
        except Exception as exc:  # noqa: BLE001
            return None, LoadFailure(directory.name, str(directory), [f"{type(exc).__name__}: {exc}"])

        try:
            content_hash = package.compute_content_hash()
            if package.manifest.content_hash and package.manifest.content_hash != content_hash:
                # Not fatal, but worth shouting about: it means the package was
                # edited without rebuilding, so any pinned learner state is wrong.
                log.warning(
                    "content_hash_mismatch",
                    subject_id=package.id,
                    manifest_hash=package.manifest.content_hash,
                    computed_hash=content_hash,
                )
            runtime = assemble.subject_runtime(package, content_hash)
            loaded = LoadedSubject(
                package=package,
                content_hash=content_hash,
                path=Path(directory),
                loaded_at=datetime.now(timezone.utc),
                runtime=runtime,
                concept_order=assemble.concept_order(package),
                concept_module=_concept_module_index(package),
            )
        except Exception as exc:  # noqa: BLE001
            return None, LoadFailure(package.id, str(directory), [f"assembly failed: {type(exc).__name__}: {exc}"])

        return loaded, None

    async def mirror_to_cache(self) -> None:
        """Write each assembled runtime into Redis under ``subject:{id}:{hash}``.

        The content hash in the key is what makes this self-invalidating: a changed
        package writes a new key and the stale one expires on its own, so a reload
        never has to reason about eviction.
        """
        for subject in self._subjects.values():
            await cache.set_json(
                cache.subject_runtime_key(subject.package.id, subject.content_hash),
                subject.runtime.model_dump(mode="json"),
                cache.TTL_SUBJECT_RUNTIME,
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @property
    def failures(self) -> list[LoadFailure]:
        return list(self._failures)

    def subject_ids(self) -> list[str]:
        return sorted(self._subjects)

    def all_subjects(self) -> list[LoadedSubject]:
        return sorted(self._subjects.values(), key=lambda s: (s.package.manifest.domain.id, s.package.manifest.title))

    def get(self, subject_id: str) -> LoadedSubject:
        try:
            return self._subjects[subject_id]
        except KeyError:
            raise NotFound(f"unknown subject {subject_id!r}") from None

    def find(self, subject_id: str) -> LoadedSubject | None:
        return self._subjects.get(subject_id)

    def package(self, subject_id: str) -> SubjectPackage:
        return self.get(subject_id).package

    def concept(self, subject_id: str, concept_id: str):
        package = self.package(subject_id)
        concept = package.concepts.get(concept_id)
        if concept is None:
            raise NotFound(f"unknown concept {concept_id!r}")
        return concept

    def task(self, task_id: str) -> tuple[str, PracticeTask]:
        """Resolve a globally unique practice id to ``(subject_id, task)``.

        Practice ids are namespaced by subject by convention, so a flat index is
        safe and saves the caller having to know the subject to fetch a task.
        """
        subject_id = self._task_owner.get(task_id)
        if subject_id is None:
            raise NotFound(f"unknown practice task {task_id!r}")
        return subject_id, self._subjects[subject_id].package.practice[task_id]

    def project(self, subject_id: str, project_id: str) -> Project:
        project = self.package(subject_id).projects.get(project_id)
        if project is None:
            raise NotFound(f"unknown project {project_id!r}")
        return project

    def assessment(self, subject_id: str, assessment_id: str) -> Assessment:
        assessment = self.package(subject_id).assessments.get(assessment_id)
        if assessment is None:
            raise NotFound(f"unknown assessment {assessment_id!r}")
        return assessment

    def skill(self, subject_id: str, skill_id: str) -> Skill:
        skill = self.package(subject_id).skill(skill_id)
        if skill is None:
            raise NotFound(f"unknown skill {skill_id!r}")
        return skill

    def skills(self, subject_id: str) -> list[Skill]:
        return list(self.package(subject_id).curriculum.skills)

    def find_concept_anywhere(self, concept_id: str):
        """Cross-subject lookup, used by compare mode via ``Concept.analogues``."""
        for subject in self._subjects.values():
            concept = subject.package.concepts.get(concept_id)
            if concept is not None:
                return subject.package.id, concept
        return None

    def resolve_runtime(self, kind: str, version: str | None = None) -> RuntimeSpec | None:
        """Find the pinned runner image for a runtime kind.

        Subject manifests are the source of truth; the platform defaults only cover
        ad-hoc runs from a lesson snippet, where no subject has been named.
        """
        kind = assemble.enum_value(kind)
        for subject in self._subjects.values():
            for spec in subject.package.manifest.runtimes:
                if assemble.enum_value(spec.kind) != kind:
                    continue
                if version is None or spec.version == version:
                    return spec
        return DEFAULT_RUNTIME_IMAGES.get(kind)

    def iter_packages(self) -> Iterable[SubjectPackage]:
        return (s.package for s in self._subjects.values())


def _concept_module_index(package: SubjectPackage) -> dict[str, tuple[str, str, str, str]]:
    index: dict[str, tuple[str, str, str, str]] = {}
    for track in package.curriculum.tracks:
        for module in track.modules:
            for concept_id in module.concepts:
                index[concept_id] = (module.id, module.title, track.id, track.title)
    return index
