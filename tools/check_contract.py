#!/usr/bin/env python3
"""Check the web app against the API it talks to, with nothing installed.

The frontend and the API are typed independently: Pydantic response models on one
side, hand-written TypeScript on the other. Nothing but discipline keeps them in
step, and the failure mode is quiet: a field renamed in a response model shows up
as ``undefined`` in the UI, which renders as a dash or an empty panel rather than
an error. That is exactly the kind of bug the honest-empty-state design hides.

So this does two things, both decidable from source text:

1. **Every call has a route.** Each ``apiFetch``/``fetchReadiness`` path in the web
   app must correspond to a real FastAPI route, same method and same path shape.
   Backend routes nothing calls are reported too, as information rather than a
   failure: the admin surface legitimately runs ahead of the UI.
2. **Every shared model agrees.** For each TypeScript object type whose name
   matches a Pydantic model (directly or through ``RENAMES``), the field sets must
   be identical. A frontend type may read a strict subset only where that is
   declared in ``SUBSETS``, with the reason.

This does not check types, only names, and it cannot see a route added by a
decorator it does not recognise. It is a floor.

Usage:
    python3 tools/check_contract.py

Exit code 1 on any mismatch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API_DIR = REPO / "apps" / "api" / "learnos_api"
WEB_SRC = REPO / "apps" / "web" / "src"
SCHEMA_PKG = REPO / "packages" / "knowledge-schema"

#: TS type name -> (python module filename, python class name). The API suffixes
#: response models with ``Out`` inconsistently, so these pairs are declared rather
#: than guessed.
RENAMES: dict[str, tuple[str, str]] = {
    "SkillMasteryOut": ("progress.py", "SkillProgressOut"),
    "CatalogSubject": ("catalog.py", "CatalogSubjectOut"),
    "CatalogDomain": ("catalog.py", "CatalogDomainOut"),
    "SearchResult": ("search.py", "SearchResultOut"),
    "Recommendation": ("graph.py", "RecommendationOut"),
}

#: TS types that deliberately read fewer fields than the wire carries. Extra
#: fields on the wire are harmless; the reason is recorded so a future reader can
#: tell an intentional subset from an oversight.
SUBSETS: dict[str, str] = {
    "DimensionScore": "the UI needs score + measured; evidence counts are not rendered",
}

#: Models the frontend *sends* rather than receives. Omitting a field with a
#: server-side default is correct here, so only a **required** backend field the
#: frontend cannot supply is a defect.
REQUEST_MODELS: set[str] = {
    "ExecutionRequest",
    "SandboxLimits",
    "SubmittedFile",
}

#: Names that collide between the two sides without describing the same payload.
IGNORE: set[str] = set()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def backend_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    api_pkg = API_DIR / "api"
    versioned = ""
    init = api_pkg / "__init__.py"
    if init.is_file():
        match = re.search(r'APIRouter\(\s*prefix="([^"]*)"', init.read_text(encoding="utf-8"))
        versioned = match.group(1) if match else ""
    for path in sorted(api_pkg.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        prefix_match = re.search(r'APIRouter\(\s*prefix="([^"]*)"', text)
        prefix = prefix_match.group(1) if prefix_match else ""
        # The health router is mounted on the app directly, outside /api/v1.
        base = "" if path.name == "health.py" else versioned
        for match in re.finditer(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"', text):
            routes.add((match.group(1).upper(), normalize(base + prefix + match.group(2))))
    return routes


def frontend_calls() -> set[tuple[str, str, str]]:
    """(method, path, source file) for every call the web app makes."""
    calls: set[tuple[str, str, str]] = set()
    files = [p for p in WEB_SRC.rglob("*.ts*") if p.suffix in (".ts", ".tsx")]
    versioned = "/api/v1"
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(WEB_SRC).as_posix()
        for match in re.finditer(r'apiFetch<[^>]*>\(\s*(`[^`]*`|"[^"]*")([^;]*?)\)', text, re.S):
            raw, rest = match.group(1).strip("`\""), match.group(2)
            method = re.search(r'method:\s*"(\w+)"', rest)
            calls.add(((method.group(1).upper() if method else "GET"), normalize(versioned + raw), rel))
        for match in re.finditer(r'fetchReadiness<[^>]*>\(\s*"([^"]*)"', text):
            calls.add(("GET", normalize(match.group(1)), rel))
    return calls


def normalize(path: str) -> str:
    """Collapse every dynamic segment so a template and a route can be compared."""
    path = path.split("?")[0]
    path = re.sub(r'\$\{[^}]*\}', "*", path)
    path = re.sub(r'\{[^}]*\}', "*", path)
    return path.rstrip("/") or "/"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def pydantic_models() -> dict[str, tuple[set[str], set[str], str]]:
    """Model name -> (all field names, required field names, source filename).

    Both sets include inherited fields. "Required" means the declaration carries
    no ``=`` default, which is what decides whether the frontend may omit it from
    a request body.
    """
    raw: dict[str, tuple[set[str], set[str], list[str], str]] = {}
    files = list((API_DIR / "schemas").glob("*.py")) + list(SCHEMA_PKG.rglob("*.py"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'^class (\w+)\(([^)]*)\):\n(.*?)(?=^class |\Z)', text, re.S | re.M):
            name, bases, body = match.group(1), match.group(2), match.group(3)
            if name in raw:
                continue
            fields: set[str] = set()
            required: set[str] = set()
            for line in re.finditer(r'^\s{4}(\w+)\s*:\s*([^\n]*)', body, re.M):
                field, declaration = line.group(1), line.group(2)
                if field.startswith("_") or field == "model_config":
                    continue
                fields.add(field)
                if "=" not in declaration:
                    required.add(field)
            raw[name] = (fields, required, [b.strip() for b in bases.split(",") if b.strip()], path.name)

    def inherit(name: str, index: int, seen: set[str]) -> set[str]:
        if name not in raw or name in seen:
            return set()
        seen.add(name)
        collected = set(raw[name][index])
        for base in raw[name][2]:
            collected |= inherit(base.split("[")[0], index, seen)
        return collected

    return {
        name: (inherit(name, 0, set()), inherit(name, 1, set()), raw[name][3])
        for name in raw
        if inherit(name, 0, set())
    }


def ts_types() -> dict[str, set[str]]:
    """TS object type name -> its top-level field names."""
    text = (WEB_SRC / "lib" / "types.ts").read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for match in re.finditer(r'export type (\w+)\s*=\s*\{', text):
        start = match.end() - 1
        depth = 0
        body = None
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    body = text[start + 1 : index]
                    break
        if body is None:
            continue
        fields: set[str] = set()
        depth = 0
        # Split on both ; and newline so single-line types are read correctly.
        for chunk in re.split(r'[;\n]', body):
            if depth == 0:
                field = re.match(r'\s*(\w+)\??\s*:', chunk)
                if field:
                    fields.add(field.group(1))
            depth += chunk.count("{") - chunk.count("}")
        if fields:
            out[match.group(1)] = fields
    return out


# ---------------------------------------------------------------------------


def main() -> int:
    problems: list[str] = []

    routes = backend_routes()
    calls = frontend_calls()
    for method, path, source in sorted(calls):
        if (method, path) not in routes:
            problems.append(f"{source}: {method} {path} has no matching API route")

    models = pydantic_models()
    types = ts_types()
    checked = 0
    for ts_name, ts_fields in sorted(types.items()):
        if ts_name in IGNORE:
            continue
        if ts_name in RENAMES:
            module, cls = RENAMES[ts_name]
            entry = models.get(cls)
            if entry is None or entry[2] != module:
                problems.append(f"RENAMES points at {module}:{cls}, which does not exist")
                continue
            py_fields, py_required, source = entry
        elif ts_name in models:
            py_fields, py_required, source = models[ts_name]
        else:
            continue
        checked += 1
        missing = py_fields - ts_fields
        extra = ts_fields - py_fields
        if extra:
            problems.append(f"{ts_name}: frontend declares {sorted(extra)} which {source} does not send")
        if ts_name in REQUEST_MODELS:
            # Only a required field is a defect; the rest have server-side defaults.
            unsendable = sorted(missing & py_required)
            if unsendable:
                problems.append(f"{ts_name}: {source} requires {unsendable}, which the frontend cannot send")
        elif missing and ts_name not in SUBSETS:
            problems.append(f"{ts_name}: {source} sends {sorted(missing)} which the frontend type omits")

    uncalled = sorted(routes - {(m, p) for m, p, _ in calls})

    if problems:
        for problem in problems:
            print(problem)
        print(f"\n{len(problems)} contract problem(s)")
        return 1

    print(f"ok: {len(calls)} call sites all map to {len(routes)} API routes; {checked} shared models agree")
    for name, reason in sorted(SUBSETS.items()):
        if name in types:
            print(f"    subset by design: {name} ({reason})")
    if uncalled:
        print(f"\n{len(uncalled)} API route(s) the web app does not call yet:")
        for method, path in uncalled:
            print(f"    {method:6} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
