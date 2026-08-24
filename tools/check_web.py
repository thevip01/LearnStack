#!/usr/bin/env python3
"""Structural checks for the web app that do not need node_modules.

Why this exists: the Python side already has ``tools/check_imports.py`` for the
same reason: the frontend's dependencies cannot always be installed (air-gapped
checkout, CI without a registry, this repo's own sandbox), and without them
``tsc`` will not run. But most defects in a codebase this size are structural
rather than type-level: an import left pointing at a moved file, a symbol renamed
in one module and still imported by four, a panel added to ``PanelType`` and
forgotten in the registry, a hook called in a module that a server component
imports. Every one of those is decidable from the source text alone.

What it checks:

1. Every intra-repo import resolves to a real file.
2. Every *named* import is actually exported by the module it comes from,
   following ``export … from`` re-exports one level.
3. ``PANEL_REGISTRY`` covers ``PanelType`` exactly: no missing key, no extra.
   This is the mechanism that keeps the runtime generic, so a hole in it is a
   runtime crash on some subject's layout, not a compile error.
4. Every route in ``lib/routes.ts`` has a page under ``app/``.
5. The architectural mandate: no subject-specific branching anywhere.
6. The server/client boundary: a module reachable from a server entry without
   crossing a ``"use client"`` file may not call React hooks. This is the class
   of error that fails ``next build`` rather than ``tsc``, so it is worth
   catching here.

What it deliberately does not do: type checking. It is a floor, not a
replacement for ``tsc --noEmit``.

Usage:
    python3 tools/check_web.py [web_src_dir]

Exit code 1 if anything is wrong.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO / "apps" / "web" / "src"

#: Files Next treats as an entry point into a route. `error` and `global-error`
#: are excluded on purpose: React requires them to be client components, so they
#: are boundaries rather than server roots.
SERVER_ENTRY_NAMES = {"page.tsx", "layout.tsx", "template.tsx", "default.tsx", "not-found.tsx", "loading.tsx"}

HOOK_CALL = re.compile(r'\buse[A-Z]\w*\s*\(')
EVENT_PROP = re.compile(r'\son[A-Z]\w*\s*=\s*\{')
IMPORT_FROM = re.compile(r'import\s+(?:type\s+)?(?:([\w*\s{},$]+?)\s+from\s+)?"([^"]+)"', re.S)
NAMED_BLOCK = re.compile(r'\{([^}]*)\}', re.S)
REEXPORT = re.compile(r'export\s+(?:\*|\{[^}]*\})\s+from\s+"([^"]+)"')


def source_files(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*.ts*") if p.suffix in (".ts", ".tsx") and "node_modules" not in p.parts)


def resolve(spec: str, importer: Path, src: Path) -> Path | None:
    """Mirror the tsconfig paths mapping: `@/x` -> `src/x`, plus relative specs."""
    if spec.startswith("@/"):
        base = src / spec[2:]
    elif spec.startswith("."):
        base = (importer.parent / spec).resolve()
    else:
        return None  # a package; not ours to verify
    for candidate in (
        base.with_suffix(".ts"),
        base.with_suffix(".tsx"),
        base / "index.ts",
        base / "index.tsx",
    ):
        if candidate.is_file():
            return candidate
    return base  # unresolvable; caller reports it


def exported_names(path: Path, src: Path, _seen: set[Path] | None = None) -> set[str]:
    """Top-level exports of a module, following `export … from` one level deep."""
    seen = _seen or set()
    if path in seen or not path.is_file():
        return set()
    seen.add(path)
    text = path.read_text(encoding="utf-8")
    names: set[str] = set()
    for match in re.finditer(
        r'^export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|type|interface|enum|let|var)\s+(\w+)',
        text,
        re.M,
    ):
        names.add(match.group(1))
    for match in re.finditer(r'^export\s*\{([^}]*)\}(?!\s*from)', text, re.M):
        for part in match.group(1).split(","):
            part = part.strip()
            if part:
                names.add(part.split()[-1])
    if re.search(r'^export\s+default', text, re.M):
        names.add("default")
    # Re-exports: `export { a } from "./x"` names a, `export * from "./x"` pulls all.
    for match in re.finditer(r'export\s+\{([^}]*)\}\s+from\s+"([^"]+)"', text):
        for part in match.group(1).split(","):
            part = part.strip()
            if part:
                names.add(part.split()[-1])
    for match in re.finditer(r'export\s+\*\s+from\s+"([^"]+)"', text):
        target = resolve(match.group(1), path, src)
        if target:
            names |= exported_names(target, src, seen)
    return names


def imports_of(text: str) -> list[tuple[str, list[str]]]:
    """(specifier, [named imports]) for every static import in a file."""
    out: list[tuple[str, list[str]]] = []
    for match in IMPORT_FROM.finditer(text):
        clause, spec = match.group(1) or "", match.group(2)
        named: list[str] = []
        block = NAMED_BLOCK.search(clause)
        if block:
            for raw in block.group(1).split(","):
                raw = re.sub(r'^\s*type\s+', '', raw.strip())
                if raw:
                    named.append(raw.split(" as ")[0].strip())
        out.append((spec, named))
    return out


def check_imports(files: list[Path], src: Path) -> list[str]:
    problems: list[str] = []
    cache: dict[Path, set[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for spec, named in imports_of(text):
            target = resolve(spec, path, src)
            if target is None:
                continue
            if not target.is_file():
                problems.append(f"{path.relative_to(src)}: import '{spec}' does not resolve to a file")
                continue
            if target not in cache:
                cache[target] = exported_names(target, src)
            for name in named:
                if name and name not in cache[target]:
                    problems.append(f"{path.relative_to(src)}: '{name}' is not exported by '{spec}'")
    return problems


def check_panel_registry(src: Path) -> list[str]:
    types_file = src / "lib" / "types.ts"
    registry_file = src / "components" / "runtime" / "PanelRegistry.tsx"
    if not types_file.is_file() or not registry_file.is_file():
        return [f"cannot find {types_file.name} / {registry_file.name}"]
    declared = re.search(r'export type PanelType\s*=\s*(.*?);', types_file.read_text(encoding="utf-8"), re.S)
    if not declared:
        return ["lib/types.ts: no PanelType union found"]
    panel_types = set(re.findall(r'"([a-z0-9_]+)"', declared.group(1)))

    text = registry_file.read_text(encoding="utf-8")
    # Every `Record<PanelType, …>` literal must be exhaustive, not just the
    # component registry: a map missing a key returns undefined at runtime, and
    # TypeScript only catches that when the annotation is present *and* tsc runs.
    maps = list(re.finditer(r'(?:const|let)\s+(\w+)\s*:\s*Record<\s*PanelType\s*,', text))
    if not maps:
        return ["PanelRegistry.tsx: no Record<PanelType, …> map found"]

    problems = []
    for match in maps:
        brace = text.find("{", match.end())
        if brace < 0:
            continue
        depth = 0
        for index in range(brace, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    body = text[brace + 1 : index]
                    break
        else:
            continue
        keys = set(re.findall(r'^\s+([a-z0-9_]+)\s*:', body, re.M))
        name = match.group(1)
        for missing in sorted(panel_types - keys):
            problems.append(f"PanelRegistry.tsx: {name} has no entry for PanelType '{missing}'")
        for extra in sorted(keys - panel_types):
            problems.append(f"PanelRegistry.tsx: {name} key '{extra}' is not a PanelType")
    return problems


def check_routes_have_pages(src: Path) -> list[str]:
    routes_file = src / "lib" / "routes.ts"
    if not routes_file.is_file():
        return ["lib/routes.ts is missing"]
    text = routes_file.read_text(encoding="utf-8")

    def normalize(route: str) -> tuple[str, ...]:
        """Path segments with every dynamic part collapsed to '*'.

        `/subjects/${id}/${mode}` and `app/subjects/[subjectId]/[mode]` both become
        ('subjects', '*', '*'), which is the only comparison that means anything
        once one side is a template and the other a filesystem path.
        """
        route = route.split("?")[0].split("#")[0]
        route = re.sub(r'\$\{[^}]*\}', "*", route)
        route = re.sub(r'\[[^\]]*\]', "*", route)
        # A parenthesised segment is a Next route group: organisational only, and
        # absent from the URL.
        return tuple(part for part in route.split("/") if part and part != "." and not part.startswith("("))

    #: A route is either returned from an arrow (template literal or string) or is
    #: a plain constant like `adminIngestion: "/admin/ingestion"`.
    templates = set()
    for match in re.finditer(r'=>\s*\(?\s*[`"](/[^`"]*)', text):
        templates.add(match.group(1))
    for match in re.finditer(r':\s*"(/[^"]*)"', text):
        templates.add(match.group(1))

    app = src / "app"
    pages = {normalize("/" + page.relative_to(app).parent.as_posix()) for page in app.rglob("page.tsx")}

    problems = []
    for template in sorted(templates):
        segments = normalize(template)
        # Covered by an exact match, or by a parent page that renders deeper paths.
        if any(page == segments or (len(page) < len(segments) and segments[: len(page)] == page) for page in pages):
            continue
        problems.append(f"lib/routes.ts: route '{template}' has no page under app/")
    return problems


def check_mandate(files: list[Path], src: Path) -> list[str]:
    """One generic runtime: the subject is data, never a branch."""
    problems = []
    registry = src / "components" / "runtime" / "PanelRegistry.tsx"
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(src)
        for match in re.finditer(r'(subject_?[Ii]d)\s*===\s*"', text):
            line = text[: match.start()].count("\n") + 1
            problems.append(f"{rel}:{line}: branches on a specific subject id ({match.group(1)} === \"…\")")
        if path != registry:
            for match in re.finditer(r'switch\s*\(\s*\w*\.?type\s*\)', text):
                if "panel" in text[max(0, match.start() - 200) : match.start()].lower():
                    line = text[: match.start()].count("\n") + 1
                    problems.append(f"{rel}:{line}: switches on a panel type outside the registry")
    return problems


def check_client_boundary(files: list[Path], src: Path) -> list[str]:
    """A module a server component imports may not call hooks.

    Next resolves the boundary transitively: a plain module inherits `"use client"`
    from whoever imports it, so the rule is not "every file with a hook is marked"
    but "no file reachable from a server entry without crossing a marked file
    calls a hook".
    """
    text_of = {path: path.read_text(encoding="utf-8") for path in files}
    is_client = {path: bool(re.match(r'^\s*(?:"use client"|\'use client\')', text)) for path, text in text_of.items()}

    edges: dict[Path, list[Path]] = {}
    for path, text in text_of.items():
        targets = []
        for spec, _ in imports_of(text):
            target = resolve(spec, path, src)
            if target and target.is_file() and target in text_of:
                targets.append(target)
        edges[path] = targets

    roots = [p for p in files if p.name in SERVER_ENTRY_NAMES and "app" in p.relative_to(src).parts and not is_client[p]]
    server: set[Path] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in server or is_client[current]:
            continue
        server.add(current)
        stack.extend(edges[current])

    problems = []
    for path in sorted(server):
        text = text_of[path]
        # Strip comments so prose about hooks does not trip the scan.
        stripped = re.sub(r'/\*.*?\*/|//[^\n]*', "", text, flags=re.S)
        hook = HOOK_CALL.search(stripped)
        if hook:
            line = stripped[: hook.start()].count("\n") + 1
            problems.append(
                f"{path.relative_to(src)}:{line}: calls {hook.group(0)[:-1].strip()}() but is reachable from a "
                f"server entry: add \"use client\" here or to the importer"
            )
        event = EVENT_PROP.search(stripped)
        if event:
            line = stripped[: event.start()].count("\n") + 1
            problems.append(f"{path.relative_to(src)}:{line}: passes an event handler prop in a server module")
    return problems


def main(argv: list[str]) -> int:
    src = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_SRC
    if not src.is_dir():
        print(f"not a directory: {src}")
        return 1
    files = source_files(src)
    if not files:
        print(f"no .ts/.tsx files under {src}")
        return 1

    groups = {
        "imports": check_imports(files, src),
        "panel registry": check_panel_registry(src),
        "routes": check_routes_have_pages(src),
        "generic-runtime mandate": check_mandate(files, src),
        "server/client boundary": check_client_boundary(files, src),
    }

    total = sum(len(v) for v in groups.values())
    if total:
        for label, problems in groups.items():
            if problems:
                print(f"\n{label}:")
                for problem in problems:
                    print(f"  {problem}")
        print(f"\n{total} problem(s) across {len(files)} files")
        return 1

    print(f"ok: {len(files)} files, every import resolves, registry exhaustive, boundary clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
