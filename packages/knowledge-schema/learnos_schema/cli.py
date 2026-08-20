"""``learnos-validate`` — validate subject packages and export JSON Schema.

This is what CI runs. A package that does not pass this never reaches a learner.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from .concept import Concept
from .curriculum import Curriculum
from .ingestion import ExtractionCandidate, SourceSpec
from .manifest import SubjectManifest
from .package import PackageValidationError, SubjectPackage, discover_packages, load_subject_package
from .practice import PracticeTask
from .project import Assessment, Project
from .ui import UISchema

EXPORTABLE = {
    "subject-manifest": SubjectManifest,
    "ui-schema": UISchema,
    "curriculum": Curriculum,
    "concept": Concept,
    "practice-task": PracticeTask,
    "project": Project,
    "assessment": Assessment,
    "subject-package": SubjectPackage,
    "source-spec": SourceSpec,
    "extraction-candidate": ExtractionCandidate,
}


def _validate(paths: list[Path], strict: bool) -> int:
    failures = 0
    targets: list[Path] = []
    for path in paths:
        if (path / "manifest.json").is_file():
            targets.append(path)
        else:
            targets.extend(discover_packages(path))

    if not targets:
        print(f"no subject packages found under {[str(p) for p in paths]}", file=sys.stderr)
        return 1

    for directory in targets:
        try:
            package = load_subject_package(directory)
        except PackageValidationError as exc:
            failures += 1
            print(f"FAIL {directory}")
            for problem in exc.problems:
                print(f"     {problem}")
            continue
        except ValidationError as exc:
            failures += 1
            print(f"FAIL {directory}")
            for error in exc.errors():
                loc = ".".join(str(p) for p in error["loc"])
                print(f"     {loc}: {error['msg']}")
            continue

        warnings = _lint(package)
        status = "OK  "
        if warnings and strict:
            failures += 1
            status = "FAIL"
        print(
            f"{status} {package.id} v{package.manifest.version} "
            f"({len(package.concepts)} concepts, {len(package.practice)} practice, "
            f"{len(package.projects)} projects, {len(package.assessments)} assessments)"
        )
        print(f"     content_hash {package.compute_content_hash()}")
        for warning in warnings:
            print(f"     warn: {warning}")

    return 1 if failures else 0


def _dim(value: object) -> str:
    """Dimension values arrive as enums or as plain strings; normalise to string."""
    return getattr(value, "value", value)  # type: ignore[return-value]


def _lint(package: SubjectPackage) -> list[str]:
    """Soft checks: things that are legal but probably wrong."""
    warnings: list[str] = []

    orphans = set(package.concepts) - set(package.curriculum.concept_ids())
    if orphans:
        warnings.append(f"{len(orphans)} concept(s) not reachable from any module: {sorted(orphans)[:5]}")

    unpractised = [c.id for c in package.concepts.values() if not c.practice]
    if unpractised:
        warnings.append(f"{len(unpractised)} concept(s) have no practice attached: {sorted(unpractised)[:5]}")

    for skill in package.curriculum.skills:
        weights = package.weights_for_skill(skill.id)
        # Dimension values may be enums or plain strings depending on how the
        # package was constructed, so compare on the string form throughout.
        measured = {_dim(t.evaluation.dimension) for t in package.practice_for_skill(skill.id)}
        # Retention is earned by revisiting practice that already exists; it is
        # never authored directly, so its absence is not a coverage gap.
        unreachable = sorted(
            _dim(d) for d, w in weights.items() if w > 0 and _dim(d) not in measured and _dim(d) != "retention"
        )
        if unreachable:
            warnings.append(
                f"skill {skill.id!r} weights {unreachable} but no practice measures them; its mastery ceiling is capped"
            )

    for task in package.practice.values():
        if not task.hints:
            warnings.append(f"practice {task.id!r} has no hints; learners can only pass or bounce")

    return warnings


def _export(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, model in EXPORTABLE.items():
        adapter = TypeAdapter(model)
        schema = adapter.json_schema(ref_template="#/$defs/{model}")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://learnos.dev/schemas/{name}.json"
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="learnos-validate", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Validate subject packages.")
    check.add_argument("paths", nargs="+", type=Path)
    check.add_argument("--strict", action="store_true", help="Treat lint warnings as failures.")

    export = sub.add_parser("export-schema", help="Write JSON Schema for every public model.")
    export.add_argument("--out", type=Path, default=Path("docs/schemas"))

    args = parser.parse_args(argv)
    if args.command == "check":
        return _validate(args.paths, args.strict)
    return _export(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
