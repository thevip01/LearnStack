"""The Subject Package: load once, serve many.

A package is a directory of JSON that has passed validation. This module owns
loading it, checking that every cross-reference resolves, and hashing it so a
version is reproducible.

Cross-reference validation is the part that earns its keep. Individually valid
files with a typo'd concept id produce a curriculum with a hole in it, and that
hole only shows up when a learner clicks the link.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator

from pydantic import Field, TypeAdapter

from .common import Id, LifecycleStatus, MasteryDimension, SchemaModel, SourceType
from .concept import Concept
from .curriculum import Curriculum, Skill
from .manifest import SubjectManifest
from .practice import PracticeKind, PracticeTask
from .project import Assessment, Project
from .ui import NavigationItem, PanelType, UISchema

_PRACTICE_ADAPTER: TypeAdapter[PracticeTask] = TypeAdapter(PracticeTask)


class PackageValidationError(Exception):
    """Raised with every problem found, not just the first.

    Authors fixing a package want the full list; failing on the first bad
    reference turns a five-minute fix into twenty round trips.
    """

    def __init__(self, subject_id: str, problems: list[str]) -> None:
        self.subject_id = subject_id
        self.problems = problems
        joined = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"subject package {subject_id!r} failed validation ({len(problems)} problems):\n{joined}")


class SourceRegistryEntry(SchemaModel):
    """A source the platform is willing to learn from, and how much it is trusted.

    Priority is what lets extraction resolve a contradiction between the vendor's
    own documentation and a blog post without a human in the loop.
    """

    id: Id
    title: str
    source_type: SourceType
    base_url: str | None = None
    priority: int = Field(ge=0, le=100, description="First-party docs sit at 90-100, random articles below 30.")
    license: str | None = None
    is_first_party: bool = False
    respect_robots: bool = True
    rate_limit_rps: float = Field(default=0.5, gt=0.0, le=10.0)
    notes: str | None = None


class SubjectPackage(SchemaModel):
    """Everything the runtime needs to become this subject."""

    manifest: SubjectManifest
    ui: UISchema
    curriculum: Curriculum
    concepts: dict[Id, Concept] = Field(default_factory=dict)
    practice: dict[Id, PracticeTask] = Field(default_factory=dict)
    projects: dict[Id, Project] = Field(default_factory=dict)
    assessments: dict[Id, Assessment] = Field(default_factory=dict)
    sources: dict[Id, SourceRegistryEntry] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def dimension_weights(self) -> dict[MasteryDimension, float]:
        from .mastery import DEFAULT_DIMENSION_WEIGHTS

        return self.manifest.dimension_weights or DEFAULT_DIMENSION_WEIGHTS

    def skill(self, skill_id: str) -> Skill | None:
        return self.curriculum.skill_index().get(skill_id)

    def weights_for_skill(self, skill_id: str) -> dict[MasteryDimension, float]:
        skill = self.skill(skill_id)
        if skill and skill.dimension_weights:
            return skill.dimension_weights
        return self.dimension_weights

    def navigation(self) -> list[NavigationItem]:
        """Flatten the curriculum into the sidebar's shape, once, server-side."""
        items: list[NavigationItem] = []
        for track in self.curriculum.tracks:
            items.append(NavigationItem(id=track.id, title=track.title, kind="track", depth=0))
            for module in track.modules:
                items.append(
                    NavigationItem(
                        id=module.id,
                        title=module.title,
                        kind="module",
                        depth=1,
                        parent_id=track.id,
                        icon=module.icon,
                        estimated_minutes=module.estimated_minutes,
                    )
                )
                for concept_id in module.concepts:
                    concept = self.concepts.get(concept_id)
                    if concept is None:
                        continue
                    items.append(
                        NavigationItem(
                            id=concept.id,
                            title=concept.title,
                            kind="concept",
                            depth=2,
                            parent_id=module.id,
                            estimated_minutes=concept.estimated_minutes,
                            skills=concept.skills,
                        )
                    )
                for project_id in module.projects:
                    project = self.projects.get(project_id)
                    if project:
                        items.append(
                            NavigationItem(
                                id=project.id, title=project.title, kind="project", depth=2, parent_id=module.id
                            )
                        )
                if module.assessment_id and module.assessment_id in self.assessments:
                    assessment = self.assessments[module.assessment_id]
                    items.append(
                        NavigationItem(
                            id=assessment.id, title=assessment.title, kind="assessment", depth=2, parent_id=module.id
                        )
                    )
        return items

    def graph(self) -> dict:
        """Nodes and edges for the knowledge graph panel and readiness checks."""
        nodes: list[dict] = []
        edges: list[dict] = []
        for concept in self.concepts.values():
            nodes.append(
                {
                    "id": concept.id,
                    "kind": "concept",
                    "label": concept.title,
                    "category": concept.category,
                    "skills": concept.skills,
                }
            )
            for dep in concept.dependencies:
                edges.append({"source": dep, "target": concept.id, "kind": "composes"})
            for prereq in concept.prerequisites:
                edges.append({"source": prereq, "target": concept.id, "kind": "prerequisite"})
            for analogue in concept.analogues:
                edges.append({"source": concept.id, "target": analogue, "kind": "analogue"})
        for skill in self.curriculum.skills:
            nodes.append(
                {"id": skill.id, "kind": "skill", "label": skill.title, "difficulty": skill.difficulty}
            )
            for prereq in skill.prerequisites:
                edges.append({"source": prereq, "target": skill.id, "kind": "prerequisite"})
            for concept_id in skill.concepts:
                edges.append({"source": concept_id, "target": skill.id, "kind": "evidences"})
        known = {n["id"] for n in nodes}
        edges = [e for e in edges if e["source"] in known and e["target"] in known]
        return {"nodes": nodes, "edges": edges}

    def practice_for_concept(self, concept_id: str) -> list[PracticeTask]:
        return [t for t in self.practice.values() if t.concept_id == concept_id]

    def practice_for_skill(self, skill_id: str, kinds: set[PracticeKind] | None = None) -> list[PracticeTask]:
        tasks = [t for t in self.practice.values() if skill_id in t.skills]
        if kinds:
            wanted = {k.value if isinstance(k, PracticeKind) else k for k in kinds}
            tasks = [t for t in tasks if t.kind in wanted]
        return sorted(tasks, key=lambda t: t.difficulty)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_references(self, panel_registry: set[str] | None = None) -> list[str]:
        problems: list[str] = []
        concept_ids = set(self.concepts)
        practice_ids = set(self.practice)
        project_ids = set(self.projects)
        assessment_ids = set(self.assessments)
        skill_ids = set(self.curriculum.skill_index())
        source_ids = set(self.sources)
        runtime_kinds = {r.kind for r in self.manifest.runtimes}

        if self.curriculum.subject_id != self.manifest.id:
            problems.append(
                f"curriculum.subject_id {self.curriculum.subject_id!r} != manifest.id {self.manifest.id!r}"
            )

        for track in self.curriculum.tracks:
            for module in track.modules:
                for cid in module.concepts:
                    if cid not in concept_ids:
                        problems.append(f"module {module.id!r} references unknown concept {cid!r}")
                for pid in module.projects:
                    if pid not in project_ids:
                        problems.append(f"module {module.id!r} references unknown project {pid!r}")
                if module.assessment_id and module.assessment_id not in assessment_ids:
                    problems.append(f"module {module.id!r} references unknown assessment {module.assessment_id!r}")

        for concept in self.concepts.values():
            if concept.subject_id != self.manifest.id:
                problems.append(f"concept {concept.id!r} claims subject {concept.subject_id!r}")
            for field in ("dependencies", "prerequisites", "related"):
                for ref in getattr(concept, field):
                    if ref not in concept_ids:
                        problems.append(f"concept {concept.id!r} {field} references unknown concept {ref!r}")
            for sid in concept.skills:
                if sid not in skill_ids:
                    problems.append(f"concept {concept.id!r} references unknown skill {sid!r}")
            for pid in concept.practice:
                if pid not in practice_ids:
                    problems.append(f"concept {concept.id!r} references unknown practice task {pid!r}")
            for ref in concept.sources:
                if source_ids and ref.source_id not in source_ids:
                    problems.append(f"concept {concept.id!r} cites unregistered source {ref.source_id!r}")
            for block in concept.body:
                if getattr(block, "type", None) == "embed_practice" and block.practice_id not in practice_ids:
                    problems.append(f"concept {concept.id!r} embeds unknown practice task {block.practice_id!r}")

        for skill in self.curriculum.skills:
            for cid in skill.concepts:
                if cid not in concept_ids:
                    problems.append(f"skill {skill.id!r} references unknown concept {cid!r}")

        for task in self.practice.values():
            if task.subject_id != self.manifest.id:
                problems.append(f"practice {task.id!r} claims subject {task.subject_id!r}")
            if task.concept_id and task.concept_id not in concept_ids:
                problems.append(f"practice {task.id!r} references unknown concept {task.concept_id!r}")
            for sid in task.skills:
                if sid not in skill_ids:
                    problems.append(f"practice {task.id!r} references unknown skill {sid!r}")
            if not task.skills:
                problems.append(f"practice {task.id!r} posts no skill evidence; it can never move mastery")
            env = getattr(task, "environment", None)
            if env is not None and runtime_kinds and env.runtime not in runtime_kinds:
                problems.append(
                    f"practice {task.id!r} needs runtime {env.runtime!r} which the manifest does not declare"
                )

        for project in self.projects.values():
            for sid in project.required_skills + project.taught_skills:
                if sid not in skill_ids:
                    problems.append(f"project {project.id!r} references unknown skill {sid!r}")
            for pid in project.prerequisite_projects:
                if pid not in project_ids:
                    problems.append(f"project {project.id!r} references unknown project {pid!r}")

        for assessment in self.assessments.values():
            covered = {s.dimension for s in assessment.sections}
            if len(covered) < 2:
                problems.append(
                    f"assessment {assessment.id!r} measures only {covered}; a single-dimension assessment "
                    "cannot report meaningful mastery"
                )
            for section in assessment.sections:
                for pid in section.practice_ids:
                    if pid not in practice_ids:
                        problems.append(f"assessment section {section.id!r} references unknown practice {pid!r}")
            for sid in assessment.skills:
                if sid not in skill_ids:
                    problems.append(f"assessment {assessment.id!r} references unknown skill {sid!r}")

        registry = panel_registry or {p.value for p in PanelType}
        for mode, layout in self.ui.modes.items():
            for panel in layout.panels:
                if panel.type not in registry:
                    problems.append(f"ui mode {mode!r} uses panel type {panel.type!r} that is not in the registry")

        for mode in self.ui.modes:
            if mode not in self.manifest.modes:
                problems.append(f"ui defines mode {mode!r} which the manifest does not list")
        for mode in self.manifest.modes:
            if mode not in self.ui.modes:
                problems.append(f"manifest lists mode {mode!r} with no ui layout")

        return problems

    def assert_valid(self, panel_registry: set[str] | None = None) -> None:
        problems = self.validate_references(panel_registry)
        if problems:
            raise PackageValidationError(self.manifest.id, problems)

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def compute_content_hash(self) -> str:
        """Stable hash over content, excluding the volatile manifest fields.

        Used to decide whether a re-ingested subject actually changed, and to pin
        a learner's in-flight project to the exact package they started on.
        """
        payload = self.model_dump(mode="json", exclude={"manifest": {"generated_at", "published_at", "content_hash"}})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Loading from disk
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageValidationError(path.parent.name, [f"{path.name}: invalid JSON at line {exc.lineno}: {exc.msg}"])


def _iter_json(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    yield from sorted(p for p in directory.rglob("*.json") if not p.name.startswith("_"))


def load_subject_package(directory: str | Path, *, validate: bool = True) -> SubjectPackage:
    """Load and validate a package directory.

    ``validate=False`` exists for the ingestion pipeline, which needs to load a
    half-built draft package in order to report what is still missing.
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"subject package directory not found: {root}")

    manifest = SubjectManifest.model_validate(_read_json(root / "manifest.json"))
    ui = UISchema.model_validate(_read_json(root / manifest.ui_file))
    curriculum = Curriculum.model_validate(_read_json(root / manifest.curriculum_file))

    problems: list[str] = []

    concepts: dict[str, Concept] = {}
    for path in _iter_json(root / manifest.concepts_dir):
        concept = Concept.model_validate(_read_json(path))
        if concept.id in concepts:
            problems.append(f"duplicate concept id {concept.id!r} in {path.name}")
        concepts[concept.id] = concept

    practice: dict[str, PracticeTask] = {}
    for path in _iter_json(root / manifest.practice_dir):
        task = _PRACTICE_ADAPTER.validate_python(_read_json(path))
        if task.id in practice:
            problems.append(f"duplicate practice id {task.id!r} in {path.name}")
        practice[task.id] = task

    projects: dict[str, Project] = {}
    for path in _iter_json(root / manifest.projects_dir):
        project = Project.model_validate(_read_json(path))
        projects[project.id] = project

    assessments: dict[str, Assessment] = {}
    for path in _iter_json(root / manifest.assessments_dir):
        assessment = Assessment.model_validate(_read_json(path))
        assessments[assessment.id] = assessment

    sources: dict[str, SourceRegistryEntry] = {}
    sources_path = root / manifest.sources_file
    if sources_path.is_file():
        raw = _read_json(sources_path)
        entries = raw.get("sources", raw) if isinstance(raw, dict) else raw
        for entry in entries:
            parsed = SourceRegistryEntry.model_validate(entry)
            sources[parsed.id] = parsed

    package = SubjectPackage(
        manifest=manifest,
        ui=ui,
        curriculum=curriculum,
        concepts=concepts,
        practice=practice,
        projects=projects,
        assessments=assessments,
        sources=sources,
    )

    if validate:
        problems.extend(package.validate_references())
        if problems:
            raise PackageValidationError(manifest.id, problems)

    return package


def discover_packages(root: str | Path) -> list[Path]:
    """Find every package directory under ``root`` by looking for manifests."""
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(p.parent for p in base.rglob("manifest.json"))


def load_all_packages(root: str | Path, *, skip_unpublished: bool = False) -> dict[str, SubjectPackage]:
    packages: dict[str, SubjectPackage] = {}
    for directory in discover_packages(root):
        package = load_subject_package(directory)
        # By value, not identity: see ``SchemaModel``. As an identity check this
        # skipped every package, published ones included, and returned an empty
        # catalogue without raising.
        if skip_unpublished and package.manifest.status != LifecycleStatus.PUBLISHED:
            continue
        packages[package.id] = package
    return packages
