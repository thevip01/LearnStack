#!/usr/bin/env python3
"""Dependency-free validator for LearnOS subject packages.

Why this exists: ``learnos-validate`` is the real gate, but it needs pydantic,
and pydantic is not installable in every environment an author works in (air-gapped
CI, a laptop with no index access). Authoring a package with no feedback loop is how
you end up with sixty JSON files and a wall of validation errors, so this script
reimplements the checks that matter using nothing but the standard library.

It is deliberately *not* a hand-written copy of the schema. It parses
``packages/knowledge-schema/learnos_schema/*.py`` with :mod:`ast` and derives the
field names, requiredness, type annotations, ``Literal`` sets, enum members,
discriminated unions and ``Field(...)`` numeric bounds from the source. When someone
adds a field to ``Concept``, this validator learns about it on the next run instead
of silently drifting. Only the semantic rules encoded in ``@model_validator`` bodies
and in ``SubjectPackage.validate_references`` are transcribed by hand, and each one
names the model method it mirrors.

Usage:
    python3 subjects/validate_package.py subjects/programming/python
    python3 subjects/validate_package.py subjects            # walks for manifests
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "packages" / "knowledge-schema" / "learnos_schema"

SCALARS = {"str", "int", "float", "bool", "dict", "list", "datetime", "Any", "object"}

# Dimensions that mastery can never be authored into directly; mirrors the
# carve-out in learnos_schema.cli._lint.
NEVER_AUTHORED_DIMENSIONS = {"retention"}


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------


@dataclass
class FieldDef:
    name: str
    annotation: str
    required: bool
    constraints: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class ModelDef:
    name: str
    bases: list[str]
    own_fields: dict[str, FieldDef]


@dataclass
class Schema:
    models: dict[str, ModelDef]
    enums: dict[str, set[str]]
    aliases: dict[str, dict[str, Any]]
    constants: dict[str, Any]

    def fields(self, model: str) -> dict[str, FieldDef]:
        """Resolve inherited fields; a subclass override wins (DebugTask.kind)."""
        out: dict[str, FieldDef] = {}
        definition = self.models.get(model)
        if definition is None:
            return out
        for base in definition.bases:
            if base in self.models:
                out.update(self.fields(base))
        out.update(definition.own_fields)
        return out

    def discriminator_value(self, model: str, discriminator: str) -> str | None:
        fields = self.fields(model)
        fdef = fields.get(discriminator)
        if fdef is None:
            return None
        values = literal_values(fdef.annotation)
        return values[0] if len(values) == 1 else None


def literal_values(annotation: str) -> list[str]:
    match = re.match(r"^Literal\[(.*)\]$", annotation.strip())
    if not match:
        return []
    try:
        parsed = ast.literal_eval(f"({match.group(1)},)")
    except (ValueError, SyntaxError):
        return []
    return [str(v) for v in parsed]


def _callee(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _numeric_constraints(call: ast.Call, constants: dict[str, Any]) -> dict[str, Any]:
    keys = {"ge", "le", "gt", "lt", "min_length", "max_length", "pattern"}
    out: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg not in keys:
            continue
        if isinstance(kw.value, ast.Name) and kw.value.id in constants:
            out[kw.arg] = constants[kw.value.id]
            continue
        try:
            out[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            continue
    return out


def _has_default(value: ast.expr | None) -> bool:
    if value is None:
        return False
    if isinstance(value, ast.Call) and _callee(value.func) == "Field":
        if value.args:
            return True
        return any(kw.arg in ("default", "default_factory") for kw in value.keywords)
    return True


def _union_members(node: ast.expr) -> list[str]:
    """Flatten ``Union[A, B]`` and ``A | B`` into member names."""
    if isinstance(node, ast.Subscript) and _callee(node.value) == "Union":
        inner = node.slice
        elts = inner.elts if isinstance(inner, ast.Tuple) else [inner]
        return [ast.unparse(e) for e in elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_members(node.left) + _union_members(node.right)
    return [ast.unparse(node)]


def load_schema(schema_dir: Path) -> Schema:
    models: dict[str, ModelDef] = {}
    enums: dict[str, set[str]] = {}
    aliases: dict[str, dict[str, Any]] = {}
    constants: dict[str, Any] = {}

    sources = sorted(schema_dir.glob("*.py"))
    if not sources:
        raise SystemExit(f"no schema sources found under {schema_dir}")

    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in sources}

    # Pass 1: module-level constants, so `pattern=ID_PATTERN` resolves.
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    constants[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue

    # Pass 2: classes and type aliases.
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [_callee(b) for b in node.bases]
                if "Enum" in bases or "IntEnum" in bases:
                    members: set[str] = set()
                    for stmt in node.body:
                        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                            members.add(str(stmt.value.value))
                    enums[node.name] = members
                    continue
                own: dict[str, FieldDef] = {}
                for stmt in node.body:
                    if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                        continue
                    annotation = ast.unparse(stmt.annotation)
                    constraints: dict[str, Any] = {}
                    if isinstance(stmt.value, ast.Call) and _callee(stmt.value.func) == "Field":
                        constraints = _numeric_constraints(stmt.value, constants)
                    own[stmt.target.id] = FieldDef(
                        name=stmt.target.id,
                        annotation=annotation,
                        required=not _has_default(stmt.value),
                        constraints=constraints,
                    )
                models[node.name] = ModelDef(name=node.name, bases=bases, own_fields=own)
                continue

            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                continue
            name = node.targets[0].id
            value = node.value
            if isinstance(value, ast.Subscript) and _callee(value.value) == "Literal":
                aliases[name] = {"kind": "literal", "values": literal_values(ast.unparse(value))}
                continue
            if isinstance(value, ast.Subscript) and _callee(value.value) == "Annotated":
                inner = value.slice
                elts = list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
                if not elts:
                    continue
                head, tail = elts[0], elts[1:]
                discriminator = None
                constraints = {}
                for extra in tail:
                    if isinstance(extra, ast.Call):
                        constraints.update(_numeric_constraints(extra, constants))
                        for kw in extra.keywords:
                            if kw.arg == "discriminator":
                                try:
                                    discriminator = ast.literal_eval(kw.value)
                                except (ValueError, SyntaxError):
                                    discriminator = None
                members = _union_members(head)
                if discriminator and len(members) > 1:
                    aliases[name] = {"kind": "union", "members": members, "discriminator": discriminator}
                else:
                    aliases[name] = {
                        "kind": "constrained",
                        "base": ast.unparse(head),
                        "constraints": constraints,
                    }

    return Schema(models=models, enums=enums, aliases=aliases, constants=constants)


# ---------------------------------------------------------------------------
# Problem collection
# ---------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


# ---------------------------------------------------------------------------
# Structural validation, driven by the introspected schema
# ---------------------------------------------------------------------------


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def _strip_optional(annotation: str) -> tuple[str, bool]:
    text = annotation.strip()
    optional = False
    while True:
        if text.endswith("| None"):
            text, optional = text[: -len("| None")].strip(), True
        elif text.startswith("None |"):
            text, optional = text[len("None |") :].strip(), True
        elif text.startswith("Optional[") and text.endswith("]"):
            text, optional = text[len("Optional[") : -1].strip(), True
        else:
            break
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text, optional


def _iso_datetime_ok(value: str) -> bool:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


class StructuralValidator:
    """Walks a JSON document against an introspected model definition."""

    def __init__(self, schema: Schema, report: Report) -> None:
        self.schema = schema
        self.report = report

    # -- entry point ----------------------------------------------------
    def check_model(self, where: str, path: str, value: Any, model: str) -> None:
        if not isinstance(value, dict):
            self.report.error(where, f"{path}: expected an object for {model}, got {type(value).__name__}")
            return
        fields = self.schema.fields(model)
        if not fields:
            self.report.error(where, f"{path}: unknown model {model!r} (schema introspection found no fields)")
            return
        unknown = sorted(set(value) - set(fields))
        for key in unknown:
            self.report.error(where, f"{path}.{key}: unknown key for {model} (extra='forbid' rejects it)")
        for name, fdef in fields.items():
            if name not in value:
                if fdef.required:
                    self.report.error(where, f"{path}.{name}: required by {model} but missing")
                continue
            self.check_value(where, f"{path}.{name}", value[name], fdef.annotation, fdef.constraints)

    # -- recursive value check -----------------------------------------
    def check_value(self, where: str, path: str, value: Any, annotation: str, constraints: dict[str, Any]) -> None:
        text, optional = _strip_optional(annotation)
        if value is None:
            if not optional:
                self.report.error(where, f"{path}: null is not allowed (annotation {annotation})")
            return

        if text.startswith("list[") and text.endswith("]"):
            inner = text[len("list[") : -1]
            if not isinstance(value, list):
                self.report.error(where, f"{path}: expected a list, got {type(value).__name__}")
                return
            self._check_length(where, path, value, constraints)
            for index, item in enumerate(value):
                self.check_value(where, f"{path}[{index}]", item, inner, {})
            return

        if text.startswith("dict[") and text.endswith("]"):
            args = _split_top_level(text[len("dict[") : -1])
            if not isinstance(value, dict):
                self.report.error(where, f"{path}: expected an object, got {type(value).__name__}")
                return
            self._check_length(where, path, value, constraints)
            key_ann = args[0] if args else "str"
            val_ann = args[1] if len(args) > 1 else "Any"
            for key, item in value.items():
                self.check_value(where, f"{path}.<key>", key, key_ann, {})
                self.check_value(where, f"{path}.{key}", item, val_ann, {})
            return

        alias = self.schema.aliases.get(text)
        if alias is not None:
            if alias["kind"] == "literal":
                if value not in alias["values"]:
                    self.report.error(where, f"{path}: {value!r} not in {sorted(alias['values'])}")
                return
            if alias["kind"] == "union":
                self._check_union(where, path, value, alias)
                return
            merged = dict(alias.get("constraints", {}))
            merged.update(constraints)
            self.check_value(where, path, value, alias["base"], merged)
            return

        if text in self.schema.enums:
            if value not in self.schema.enums[text]:
                self.report.error(where, f"{path}: {value!r} not a {text} ({sorted(self.schema.enums[text])})")
            return

        if text.startswith("Literal["):
            allowed = literal_values(text)
            if value not in allowed:
                self.report.error(where, f"{path}: {value!r} not in {allowed}")
            return

        if text in self.schema.models:
            self.check_model(where, path, value, text)
            return

        self._check_scalar(where, path, value, text, constraints)

    def _check_union(self, where: str, path: str, value: Any, alias: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            self.report.error(where, f"{path}: expected an object for a discriminated union")
            return
        discriminator = alias["discriminator"]
        tag = value.get(discriminator)
        if tag is None:
            self.report.error(where, f"{path}: missing discriminator {discriminator!r}")
            return
        for member in alias["members"]:
            if self.schema.discriminator_value(member, discriminator) == tag:
                self.check_model(where, path, value, member)
                return
        known = sorted(
            v for v in (self.schema.discriminator_value(m, discriminator) for m in alias["members"]) if v
        )
        self.report.error(where, f"{path}.{discriminator}: {tag!r} is not one of {known}")

    def _check_scalar(self, where: str, path: str, value: Any, text: str, constraints: dict[str, Any]) -> None:
        if text in ("Any", "object"):
            return
        if text == "datetime":
            if not isinstance(value, str) or not _iso_datetime_ok(value):
                self.report.error(where, f"{path}: expected an ISO 8601 timestamp, got {value!r}")
            return
        if text == "str":
            if not isinstance(value, str):
                self.report.error(where, f"{path}: expected a string, got {type(value).__name__}")
                return
            self._check_length(where, path, value, constraints)
            pattern = constraints.get("pattern")
            if pattern and not re.match(pattern, value):
                self.report.error(where, f"{path}: {value!r} does not match {pattern}")
            return
        if text == "bool":
            if not isinstance(value, bool):
                self.report.error(where, f"{path}: expected a boolean, got {type(value).__name__}")
            return
        if text in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self.report.error(where, f"{path}: expected a number, got {type(value).__name__}")
                return
            if text == "int" and not float(value).is_integer():
                self.report.error(where, f"{path}: expected an integer, got {value!r}")
            self._check_bounds(where, path, value, constraints)
            return
        if text in ("dict", "list"):
            expected = dict if text == "dict" else list
            if not isinstance(value, expected):
                self.report.error(where, f"{path}: expected a {text}, got {type(value).__name__}")
            return
        # Unresolvable annotation: report rather than silently pass, so a schema
        # change that this validator cannot model is visible instead of ignored.
        self.report.warn(where, f"{path}: cannot check annotation {text!r} without pydantic")

    def _check_length(self, where: str, path: str, value: Sequence[Any] | dict, constraints: dict[str, Any]) -> None:
        minimum = constraints.get("min_length")
        maximum = constraints.get("max_length")
        if minimum is not None and len(value) < minimum:
            self.report.error(where, f"{path}: needs at least {minimum} item(s), has {len(value)}")
        if maximum is not None and len(value) > maximum:
            self.report.error(where, f"{path}: allows at most {maximum} item(s)/char(s), has {len(value)}")

    def _check_bounds(self, where: str, path: str, value: float, constraints: dict[str, Any]) -> None:
        for key, ok, label in (
            ("ge", lambda v, b: v >= b, ">="),
            ("le", lambda v, b: v <= b, "<="),
            ("gt", lambda v, b: v > b, ">"),
            ("lt", lambda v, b: v < b, "<"),
        ):
            bound = constraints.get(key)
            if bound is not None and not ok(value, bound):
                self.report.error(where, f"{path}: {value} violates {label} {bound}")


# ---------------------------------------------------------------------------
# The loaded package
# ---------------------------------------------------------------------------


@dataclass
class Package:
    root: Path
    manifest: dict
    ui: dict
    curriculum: dict
    concepts: dict[str, dict]
    practice: dict[str, dict]
    projects: dict[str, dict]
    assessments: dict[str, dict]
    sources: dict[str, dict]
    files: dict[str, Path]

    def modules(self) -> Iterator[dict]:
        for track in self.curriculum.get("tracks", []) or []:
            for module in track.get("modules", []) or []:
                yield module

    def skills(self) -> list[dict]:
        return self.curriculum.get("skills", []) or []


def _load_json(path: Path, report: Report) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.error(path.name, f"invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}")
        return None
    except OSError as exc:
        report.error(path.name, f"unreadable: {exc}")
        return None


def _iter_json(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    yield from sorted(p for p in directory.rglob("*.json") if not p.name.startswith("_"))


def load_package(root: Path, schema: Schema, report: Report) -> Package | None:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        report.error(str(root), "no manifest.json")
        return None
    manifest = _load_json(manifest_path, report)
    if not isinstance(manifest, dict):
        return None

    def named(key: str, default: str) -> str:
        value = manifest.get(key, default)
        return value if isinstance(value, str) else default

    ui = _load_json(root / named("ui_file", "ui.json"), report) or {}
    curriculum = _load_json(root / named("curriculum_file", "curriculum.json"), report) or {}

    files: dict[str, Path] = {"manifest": manifest_path}
    collections: dict[str, dict[str, dict]] = {}
    for key, dirname, entity in (
        ("concepts", named("concepts_dir", "concepts"), "concept"),
        ("practice", named("practice_dir", "practice"), "practice"),
        ("projects", named("projects_dir", "projects"), "project"),
        ("assessments", named("assessments_dir", "assessments"), "assessment"),
    ):
        bucket: dict[str, dict] = {}
        for path in _iter_json(root / dirname):
            payload = _load_json(path, report)
            if not isinstance(payload, dict):
                continue
            entity_id = payload.get("id")
            if not isinstance(entity_id, str):
                report.error(path.name, f"{entity} file has no string 'id'")
                continue
            if entity_id in bucket:
                report.error(path.name, f"duplicate {entity} id {entity_id!r}")
            bucket[entity_id] = payload
            files[entity_id] = path
            if path.stem != entity_id:
                report.error(path.name, f"filename does not match id {entity_id!r} (expected {entity_id}.json)")
        collections[key] = bucket

    sources: dict[str, dict] = {}
    sources_path = root / named("sources_file", "sources.json")
    if sources_path.is_file():
        raw = _load_json(sources_path, report)
        entries = raw.get("sources", raw) if isinstance(raw, dict) else raw
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    if entry["id"] in sources:
                        report.error(sources_path.name, f"duplicate source id {entry['id']!r}")
                    sources[entry["id"]] = entry
                else:
                    report.error(sources_path.name, "source entry is not an object with a string id")
        else:
            report.error(sources_path.name, "expected a list of sources, or {'sources': [...]}")
    else:
        report.error(str(root), f"missing {sources_path.name}")

    return Package(
        root=root,
        manifest=manifest,
        ui=ui if isinstance(ui, dict) else {},
        curriculum=curriculum if isinstance(curriculum, dict) else {},
        concepts=collections["concepts"],
        practice=collections["practice"],
        projects=collections["projects"],
        assessments=collections["assessments"],
        sources=sources,
        files=files,
    )


# ---------------------------------------------------------------------------
# Semantic checks (hand-transcribed from the model validators)
# ---------------------------------------------------------------------------


def _weights_sum_to_one(report: Report, where: str, label: str, weights: Any) -> None:
    if not isinstance(weights, dict) or not weights:
        return
    values = [v for v in weights.values() if isinstance(v, (int, float))]
    total = sum(values)
    if abs(total - 1.0) > 1e-6:
        report.error(where, f"{label} sum to {total}, expected 1.0")


def check_manifest(pkg: Package, report: Report) -> None:
    """Mirrors SubjectManifest._id_matches_parts / _weights_sum_to_one / _published_needs_hash."""
    where = "manifest.json"
    manifest = pkg.manifest
    domain = manifest.get("domain") or {}
    parts = [domain.get("id"), manifest.get("subject"), manifest.get("provider")]
    expected = ".".join(str(p) for p in parts if p)
    if manifest.get("id") != expected:
        report.error(where, f"id {manifest.get('id')!r} does not match derived id {expected!r}")
    _weights_sum_to_one(report, where, "dimension_weights", manifest.get("dimension_weights"))
    if manifest.get("status") == "published" and not manifest.get("content_hash"):
        report.error(where, "a published manifest must carry a content_hash")
    if manifest.get("content_hash") in ("sha256:PLACEHOLDER", "", None) and manifest.get("status") == "published":
        report.error(where, "content_hash is still a placeholder; run the build step to compute it")


def check_ui(pkg: Package, schema: Schema, report: Report) -> None:
    """Mirrors ModeLayout._unique_panel_ids, UISchema._default_mode_present and the
    panel-registry / mode-parity checks in SubjectPackage.validate_references."""
    where = "ui.json"
    ui = pkg.ui
    panel_types = schema.enums.get("PanelType", set())
    modes = ui.get("modes") or {}
    if not isinstance(modes, dict):
        report.error(where, "modes must be an object keyed by learning mode")
        return

    for mode, layout in modes.items():
        if not isinstance(layout, dict):
            continue
        panels = layout.get("panels") or []
        ids = [p.get("id") for p in panels if isinstance(p, dict)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            report.error(where, f"mode {mode!r} has duplicate panel ids {duplicates}")
        for panel in panels:
            if isinstance(panel, dict) and panel.get("type") not in panel_types:
                report.error(where, f"mode {mode!r} panel {panel.get('id')!r} uses unknown panel type {panel.get('type')!r}")

    for panel in ui.get("global_panels") or []:
        if isinstance(panel, dict) and panel.get("type") not in panel_types:
            report.error(where, f"global panel {panel.get('id')!r} uses unknown panel type {panel.get('type')!r}")

    default_mode = ui.get("default_mode", "learn")
    if default_mode not in modes:
        report.error(where, f"default_mode {default_mode!r} has no layout defined")

    declared = pkg.manifest.get("modes") or []
    for mode in modes:
        if mode not in declared:
            report.error(where, f"ui defines mode {mode!r} which the manifest does not list")
    for mode in declared:
        if mode not in modes:
            report.error("manifest.json", f"manifest lists mode {mode!r} with no ui layout")


def check_curriculum(pkg: Package, report: Report) -> None:
    """Mirrors Curriculum._skill_graph_is_acyclic, _module_ids_unique and Skill._weights_sum_to_one."""
    where = "curriculum.json"
    if pkg.curriculum.get("subject_id") != pkg.manifest.get("id"):
        report.error(
            where,
            f"subject_id {pkg.curriculum.get('subject_id')!r} != manifest.id {pkg.manifest.get('id')!r}",
        )

    seen_modules: set[str] = set()
    for module in pkg.modules():
        module_id = module.get("id")
        if module_id in seen_modules:
            report.error(where, f"duplicate module id {module_id!r}")
        seen_modules.add(module_id)

    skills = pkg.skills()
    index = {s.get("id"): list(s.get("prerequisites") or []) for s in skills}
    unknown = {p for prereqs in index.values() for p in prereqs} - set(index)
    if unknown:
        report.error(where, f"skill prerequisites reference unknown skills: {sorted(unknown)}")

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in index}

    def visit(node: str, path: list[str]) -> None:
        colour[node] = GREY
        for nxt in index.get(node, []):
            if nxt not in colour:
                continue
            if colour[nxt] == GREY:
                report.error(where, "skill prerequisite cycle: " + " -> ".join(path + [node, nxt]))
                continue
            if colour[nxt] == WHITE:
                visit(nxt, path + [node])
        colour[node] = BLACK

    for node in index:
        if colour[node] == WHITE:
            visit(node, [])

    for skill in skills:
        _weights_sum_to_one(report, where, f"skill {skill.get('id')!r} dimension_weights", skill.get("dimension_weights"))

    default_track = pkg.curriculum.get("default_track")
    track_ids = {t.get("id") for t in pkg.curriculum.get("tracks") or []}
    if default_track and default_track not in track_ids:
        report.error(where, f"default_track {default_track!r} is not a declared track")


def _blocks(concept: dict) -> Iterable[dict]:
    for block in concept.get("body") or []:
        if isinstance(block, dict):
            yield block


def check_concepts(pkg: Package, report: Report) -> None:
    """Mirrors Concept._no_self_reference / _must_cite_something plus the concept
    branch of SubjectPackage.validate_references."""
    subject_id = pkg.manifest.get("id")
    for concept_id, concept in sorted(pkg.concepts.items()):
        where = pkg.files[concept_id].name
        if concept.get("subject_id") != subject_id:
            report.error(where, f"claims subject {concept.get('subject_id')!r}, expected {subject_id!r}")

        for relation in ("dependencies", "prerequisites", "related", "analogues"):
            refs = concept.get(relation) or []
            if concept_id in refs:
                report.error(where, f"lists itself in {relation}")
            if relation == "analogues":
                continue  # cross-subject by design; not resolvable inside one package
            for ref in refs:
                if ref not in pkg.concepts:
                    report.error(where, f"{relation} references unknown concept {ref!r}")

        cited = bool(concept.get("sources")) or any(block.get("sources") for block in _blocks(concept))
        if not cited:
            report.error(where, "has no sources; every concept must be traceable to at least one source")

        refs = list(concept.get("sources") or [])
        for block in _blocks(concept):
            refs.extend(block.get("sources") or [])
        for error in concept.get("common_errors") or []:
            if isinstance(error, dict):
                refs.extend(error.get("sources") or [])
        for ref in refs:
            if isinstance(ref, dict) and pkg.sources and ref.get("source_id") not in pkg.sources:
                report.error(where, f"cites unregistered source {ref.get('source_id')!r}")

        for skill_id in concept.get("skills") or []:
            if skill_id not in {s.get("id") for s in pkg.skills()}:
                report.error(where, f"references unknown skill {skill_id!r}")
        for practice_id in concept.get("practice") or []:
            if practice_id not in pkg.practice:
                report.error(where, f"references unknown practice task {practice_id!r}")

        for index, block in enumerate(_blocks(concept)):
            if block.get("type") == "embed_practice" and block.get("practice_id") not in pkg.practice:
                report.error(where, f"body[{index}] embeds unknown practice task {block.get('practice_id')!r}")


def check_practice(pkg: Package, report: Report) -> None:
    """Mirrors PracticeTaskBase._hint_ladder_ordered, Evaluation._rubric_weights,
    SourceFile._safe_path, the question answer validators, and the practice branch of
    SubjectPackage.validate_references."""
    subject_id = pkg.manifest.get("id")
    skill_ids = {s.get("id") for s in pkg.skills()}
    runtime_kinds = {r.get("kind") for r in pkg.manifest.get("runtimes") or []}

    for task_id, task in sorted(pkg.practice.items()):
        where = pkg.files[task_id].name
        if task.get("subject_id") != subject_id:
            report.error(where, f"claims subject {task.get('subject_id')!r}, expected {subject_id!r}")
        concept_id = task.get("concept_id")
        if concept_id and concept_id not in pkg.concepts:
            report.error(where, f"references unknown concept {concept_id!r}")
        skills = task.get("skills") or []
        if not skills:
            report.error(where, "posts no skill evidence; it can never move mastery")
        for skill_id in skills:
            if skill_id not in skill_ids:
                report.error(where, f"references unknown skill {skill_id!r}")

        environment = task.get("environment")
        if isinstance(environment, dict):
            runtime = environment.get("runtime", "python")
            if runtime_kinds and runtime not in runtime_kinds:
                report.error(where, f"needs runtime {runtime!r} which the manifest does not declare")
            if environment.get("egress_allowlist") and environment.get("network") != "egress_allowlist":
                report.error(where, "egress_allowlist set but network mode is not 'egress_allowlist'")

        hints = task.get("hints") or []
        levels = [h.get("level") for h in hints if isinstance(h, dict)]
        if levels != sorted(set(levels), key=lambda x: (x is None, x)):
            report.error(where, f"hint levels must be unique and ascending, got {levels}")
        if not hints:
            report.error(where, "has no hints; learners can only pass or bounce")
        else:
            if len(hints) < 3:
                report.error(where, f"hint ladder has {len(hints)} level(s); the authoring rule is 3")
            if not hints[-1].get("reveals_solution"):
                report.error(where, "the last hint must set reveals_solution: true")
            if any(h.get("reveals_solution") for h in hints[:-1]):
                report.error(where, "only the last hint may set reveals_solution")

        evaluation = task.get("evaluation") or {}
        rubric = evaluation.get("rubric") or []
        if rubric:
            total = sum(c.get("weight", 0) for c in rubric if isinstance(c, dict))
            if abs(total - 1.0) > 1e-6:
                report.error(where, f"rubric weights sum to {total}, expected 1.0")

        for key in ("starter_files", "solution_files", "broken_files", "initial_filesystem"):
            for source_file in task.get(key) or []:
                path = source_file.get("path", "") if isinstance(source_file, dict) else ""
                if path.startswith("/") or ".." in path.split("/"):
                    report.error(where, f"{key} contains unsafe file path {path!r}")

        for ref in task.get("sources") or []:
            if isinstance(ref, dict) and pkg.sources and ref.get("source_id") not in pkg.sources:
                report.error(where, f"cites unregistered source {ref.get('source_id')!r}")

        _check_questions(where, task, pkg, report)
        _check_tests(where, task.get("tests") or [], report)


def _check_questions(where: str, task: dict, pkg: Package, report: Report) -> None:
    seen: set[str] = set()
    skill_ids = {s.get("id") for s in pkg.skills()}
    for question in task.get("questions") or []:
        if not isinstance(question, dict):
            continue
        qid = question.get("id")
        if qid in seen:
            report.error(where, f"duplicate question id {qid!r}")
        seen.add(qid)
        for skill_id in question.get("skills") or []:
            if skill_id not in skill_ids:
                report.error(where, f"question {qid!r} references unknown skill {skill_id!r}")
        for ref in question.get("sources") or []:
            if isinstance(ref, dict) and pkg.sources and ref.get("source_id") not in pkg.sources:
                report.error(where, f"question {qid!r} cites unregistered source {ref.get('source_id')!r}")

        qtype = question.get("type")
        answer = question.get("answer")
        if qtype == "mcq":
            option_ids = {o.get("id") for o in question.get("options") or []}
            if answer not in option_ids:
                report.error(where, f"question {qid!r} answer {answer!r} is not one of its options")
        elif qtype == "multi_select":
            option_ids = {o.get("id") for o in question.get("options") or []}
            unknown = sorted(set(answer or []) - option_ids)
            if unknown:
                report.error(where, f"question {qid!r} answers {unknown} are not options")
        elif qtype == "ordering":
            item_ids = [o.get("id") for o in question.get("items") or []]
            if sorted(answer or []) != sorted(item_ids):
                report.error(where, f"question {qid!r} answer must be a permutation of its item ids {item_ids}")
        elif qtype == "matching":
            left_ids = {o.get("id") for o in question.get("left") or []}
            right_ids = {o.get("id") for o in question.get("right") or []}
            if not isinstance(answer, dict):
                report.error(where, f"question {qid!r} matching answer must be an object")
            else:
                for key, value in answer.items():
                    if key not in left_ids:
                        report.error(where, f"question {qid!r} answer key {key!r} is not a left item")
                    if value not in right_ids:
                        report.error(where, f"question {qid!r} answer value {value!r} is not a right item")
                missing = sorted(left_ids - set(answer))
                if missing:
                    report.error(where, f"question {qid!r} leaves left items {missing} unmatched")
        elif qtype == "fill_blank":
            template = question.get("template", "") or ""
            blanks = len(set(re.findall(r"\{\{(\d+)\}\}", template)))
            if not isinstance(answer, list) or len(answer) != blanks:
                report.error(
                    where,
                    f"question {qid!r} template has {blanks} blank(s) but answer has "
                    f"{len(answer) if isinstance(answer, list) else 'none'}",
                )
        elif qtype == "short_answer":
            if not answer:
                report.error(where, f"question {qid!r} short_answer needs at least one accepted answer")


def _check_tests(where: str, tests: Iterable[Any], report: Report) -> None:
    seen: set[str] = set()
    for test in tests:
        if not isinstance(test, dict):
            continue
        test_id = test.get("id")
        if test_id in seen:
            report.error(where, f"duplicate test id {test_id!r}")
        seen.add(test_id)
        if test.get("visible") and not test.get("body"):
            report.error(where, f"test {test_id!r} is visible but has no body to show")
        if not test.get("visible") and not test.get("body"):
            report.error(where, f"test {test_id!r} has no body; there is nothing to run")


def check_projects(pkg: Package, report: Report) -> None:
    skill_ids = {s.get("id") for s in pkg.skills()}
    for project_id, project in sorted(pkg.projects.items()):
        where = pkg.files[project_id].name
        if project.get("subject_id") != pkg.manifest.get("id"):
            report.error(where, f"claims subject {project.get('subject_id')!r}")
        for skill_id in (project.get("required_skills") or []) + (project.get("taught_skills") or []):
            if skill_id not in skill_ids:
                report.error(where, f"references unknown skill {skill_id!r}")
        for prerequisite in project.get("prerequisite_projects") or []:
            if prerequisite not in pkg.projects:
                report.error(where, f"references unknown project {prerequisite!r}")
        evaluation = project.get("evaluation") or {}
        rubric = evaluation.get("rubric") or []
        if rubric:
            total = sum(c.get("weight", 0) for c in rubric if isinstance(c, dict))
            if abs(total - 1.0) > 1e-6:
                report.error(where, f"evaluation rubric weights sum to {total}, expected 1.0")
        milestone_ids: set[str] = set()
        for milestone in project.get("milestones") or []:
            if not isinstance(milestone, dict):
                continue
            if milestone.get("id") in milestone_ids:
                report.error(where, f"duplicate milestone id {milestone.get('id')!r}")
            milestone_ids.add(milestone.get("id"))
            for skill_id in milestone.get("skills") or []:
                if skill_id not in skill_ids:
                    report.error(where, f"milestone {milestone.get('id')!r} references unknown skill {skill_id!r}")
            _check_tests(where, milestone.get("tests") or [], report)
        for source_file in project.get("starter_files") or []:
            path = source_file.get("path", "") if isinstance(source_file, dict) else ""
            if path.startswith("/") or ".." in path.split("/"):
                report.error(where, f"starter_files contains unsafe file path {path!r}")
        for ref in project.get("sources") or []:
            if isinstance(ref, dict) and pkg.sources and ref.get("source_id") not in pkg.sources:
                report.error(where, f"cites unregistered source {ref.get('source_id')!r}")


def check_assessments(pkg: Package, report: Report) -> None:
    """Mirrors Assessment._section_weights and the assessment branch of validate_references."""
    skill_ids = {s.get("id") for s in pkg.skills()}
    for assessment_id, assessment in sorted(pkg.assessments.items()):
        where = pkg.files[assessment_id].name
        if assessment.get("subject_id") != pkg.manifest.get("id"):
            report.error(where, f"claims subject {assessment.get('subject_id')!r}")
        sections = assessment.get("sections") or []
        total = sum(s.get("weight", 0) for s in sections if isinstance(s, dict))
        if abs(total - 1.0) > 1e-6:
            report.error(where, f"section weights sum to {total}, expected 1.0")
        dimensions = {s.get("dimension") for s in sections if isinstance(s, dict)}
        if len(dimensions) < 2:
            report.error(
                where,
                f"measures only {sorted(d for d in dimensions if d)}; a single-dimension assessment "
                "cannot report meaningful mastery",
            )
        for section in sections:
            if not isinstance(section, dict):
                continue
            for practice_id in section.get("practice_ids") or []:
                if practice_id not in pkg.practice:
                    report.error(where, f"section {section.get('id')!r} references unknown practice {practice_id!r}")
        for skill_id in assessment.get("skills") or []:
            if skill_id not in skill_ids:
                report.error(where, f"references unknown skill {skill_id!r}")
        scope_id = assessment.get("scope_id")
        if scope_id:
            known = (
                {t.get("id") for t in pkg.curriculum.get("tracks") or []}
                | {m.get("id") for m in pkg.modules()}
                | skill_ids
                | {pkg.manifest.get("id")}
            )
            if scope_id not in known:
                report.error(where, f"scope_id {scope_id!r} is not a known track, module, skill or subject")


def check_module_references(pkg: Package, report: Report) -> None:
    where = "curriculum.json"
    for module in pkg.modules():
        module_id = module.get("id")
        for concept_id in module.get("concepts") or []:
            if concept_id not in pkg.concepts:
                report.error(where, f"module {module_id!r} references unknown concept {concept_id!r}")
        for project_id in module.get("projects") or []:
            if project_id not in pkg.projects:
                report.error(where, f"module {module_id!r} references unknown project {project_id!r}")
        assessment_id = module.get("assessment_id")
        if assessment_id and assessment_id not in pkg.assessments:
            report.error(where, f"module {module_id!r} references unknown assessment {assessment_id!r}")
    for skill in pkg.skills():
        for concept_id in skill.get("concepts") or []:
            if concept_id not in pkg.concepts:
                report.error(where, f"skill {skill.get('id')!r} references unknown concept {concept_id!r}")


def check_dimension_coverage(pkg: Package, report: Report) -> None:
    """The check learnos_schema.cli._lint emits as a warning, raised to an error here.

    A skill that weights a dimension no task measures has a permanently capped
    mastery ceiling, which is a content bug, not a stylistic preference.
    """
    default_weights = pkg.manifest.get("dimension_weights") or {}
    for skill in pkg.skills():
        skill_id = skill.get("id")
        weights = skill.get("dimension_weights") or default_weights
        measured = {
            (task.get("evaluation") or {}).get("dimension", "practice")
            for task in pkg.practice.values()
            if skill_id in (task.get("skills") or [])
        }
        unreachable = sorted(
            dimension
            for dimension, weight in weights.items()
            if weight > 0 and dimension not in measured and dimension not in NEVER_AUTHORED_DIMENSIONS
        )
        if unreachable:
            report.error(
                "curriculum.json",
                f"skill {skill_id!r} weights {unreachable} but no practice task measures them; "
                "its mastery ceiling is capped",
            )


def check_sources(pkg: Package, report: Report) -> None:
    """Mirrors SourceSpec._first_party_priority: a first-party source must outrank a blog."""
    where = "sources.json"
    for source_id, source in sorted(pkg.sources.items()):
        if source.get("is_first_party") and source.get("priority", 0) < 80:
            report.error(
                where,
                f"source {source_id!r} is first-party but priority {source.get('priority')} "
                "would let a blog outrank it",
            )
    used: set[str] = set()
    for concept in pkg.concepts.values():
        for ref in concept.get("sources") or []:
            if isinstance(ref, dict):
                used.add(ref.get("source_id"))
        for block in _blocks(concept):
            for ref in block.get("sources") or []:
                if isinstance(ref, dict):
                    used.add(ref.get("source_id"))
        for error in concept.get("common_errors") or []:
            for ref in (error.get("sources") or []) if isinstance(error, dict) else []:
                if isinstance(ref, dict):
                    used.add(ref.get("source_id"))
    for task in pkg.practice.values():
        for ref in task.get("sources") or []:
            if isinstance(ref, dict):
                used.add(ref.get("source_id"))
        for question in task.get("questions") or []:
            for ref in (question.get("sources") or []) if isinstance(question, dict) else []:
                if isinstance(ref, dict):
                    used.add(ref.get("source_id"))
    for project in pkg.projects.values():
        for ref in project.get("sources") or []:
            if isinstance(ref, dict):
                used.add(ref.get("source_id"))
    unused = sorted(set(pkg.sources) - used)
    if unused:
        report.warn(where, f"registered but never cited: {unused}")


def check_lint(pkg: Package, report: Report) -> None:
    """The remaining soft checks from learnos_schema.cli._lint."""
    reachable = {c for module in pkg.modules() for c in module.get("concepts") or []}
    orphans = sorted(set(pkg.concepts) - reachable)
    if orphans:
        report.error("curriculum.json", f"{len(orphans)} concept(s) not reachable from any module: {orphans}")
    unpractised = sorted(cid for cid, c in pkg.concepts.items() if not (c.get("practice") or []))
    if unpractised:
        report.error("concepts", f"{len(unpractised)} concept(s) have no practice attached: {unpractised}")

    kinds = {task.get("kind") for task in pkg.practice.values()}
    for required in ("quiz", "code", "debug"):
        if required not in kinds:
            report.warn("practice", f"no {required} tasks; the runtime's {required} dispatch is unexercised")
    question_types = {
        q.get("type")
        for task in pkg.practice.values()
        for q in task.get("questions") or []
        if isinstance(q, dict)
    }
    missing = sorted({"mcq", "multi_select", "fill_blank", "ordering", "matching", "short_answer"} - question_types)
    if missing:
        report.warn("practice", f"question types never used: {missing}")


def check_structure(pkg: Package, schema: Schema, report: Report) -> None:
    validator = StructuralValidator(schema, report)
    validator.check_model("manifest.json", "manifest", pkg.manifest, "SubjectManifest")
    validator.check_model("ui.json", "ui", pkg.ui, "UISchema")
    validator.check_model("curriculum.json", "curriculum", pkg.curriculum, "Curriculum")
    for concept_id, concept in sorted(pkg.concepts.items()):
        validator.check_model(pkg.files[concept_id].name, "concept", concept, "Concept")
    for task_id, task in sorted(pkg.practice.items()):
        validator.check_value(pkg.files[task_id].name, "task", task, "PracticeTask", {})
    for project_id, project in sorted(pkg.projects.items()):
        validator.check_model(pkg.files[project_id].name, "project", project, "Project")
    for assessment_id, assessment in sorted(pkg.assessments.items()):
        validator.check_model(pkg.files[assessment_id].name, "assessment", assessment, "Assessment")
    for source_id, source in sorted(pkg.sources.items()):
        validator.check_model("sources.json", f"sources.{source_id}", source, "SourceRegistryEntry")


def validate(root: Path, schema: Schema) -> Report:
    report = Report()
    pkg = load_package(root, schema, report)
    if pkg is None:
        return report
    check_structure(pkg, schema, report)
    check_manifest(pkg, report)
    check_ui(pkg, schema, report)
    check_curriculum(pkg, report)
    check_module_references(pkg, report)
    check_concepts(pkg, report)
    check_practice(pkg, report)
    check_projects(pkg, report)
    check_assessments(pkg, report)
    check_dimension_coverage(pkg, report)
    check_sources(pkg, report)
    check_lint(pkg, report)
    return report


def summarise(root: Path, schema: Schema) -> str:
    report = Report()
    pkg = load_package(root, schema, Report())
    if pkg is None:
        return str(root)
    del report
    concepts = len(pkg.concepts)
    skills = len(pkg.skills())
    practice = len(pkg.practice)
    return (
        f"{pkg.manifest.get('id')} v{pkg.manifest.get('version')} "
        f"({concepts} concepts, {skills} skills, {practice} practice, "
        f"{len(pkg.projects)} projects, {len(pkg.assessments)} assessments, {len(pkg.sources)} sources)"
    )


def discover(paths: Sequence[Path]) -> list[Path]:
    targets: list[Path] = []
    for path in paths:
        if (path / "manifest.json").is_file():
            targets.append(path)
        else:
            targets.extend(sorted(p.parent for p in path.rglob("manifest.json")))
    return targets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_package.py", description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Package directories, or a tree to search.")
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    args = parser.parse_args(argv)

    schema = load_schema(args.schema_dir)
    targets = discover(args.paths)
    if not targets:
        print(f"no subject packages found under {[str(p) for p in args.paths]}", file=sys.stderr)
        return 1

    failures = 0
    for root in targets:
        report = validate(root, schema)
        failed = bool(report.errors) or (args.strict and bool(report.warnings))
        failures += 1 if failed else 0
        print(f"{'FAIL' if failed else 'OK  '} {summarise(root, schema)}")
        for problem in report.errors:
            print(f"     error: {problem}")
        for problem in report.warnings:
            print(f"     warn:  {problem}")
    print(
        f"\n{len(targets)} package(s) checked, {failures} failed "
        f"(schema: {len(schema.models)} models, {len(schema.enums)} enums, {len(schema.aliases)} aliases)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
