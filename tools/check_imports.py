#!/usr/bin/env python3
"""Resolve every intra-repo import against what the target module really defines.

Why this exists: the repo's third-party dependencies cannot always be installed
(air-gapped checkouts, CI without a package index), and without them ``mypy`` and
even ``import learnos_api`` are unavailable. But the defects that actually ship in
a Python codebase this size are overwhelmingly *name* defects: a function renamed
in one module and still imported by three others, a helper that moved package, a
symbol left in ``__all__`` after deletion. Those are decidable from the AST alone.

So this walks the source tree, builds a map of every module to the names it binds
at top level, and then checks every ``from . import x`` / ``from ..y import z``
against that map. Pure stdlib, no network, no imports of the code under test.

What it deliberately does **not** do: type checking, or anything requiring the
third-party packages to be present. It is a floor, not a replacement for mypy.

Usage:
    python3 tools/check_imports.py [root ...]

Exit code 1 if anything is unresolvable.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Directories that are import roots: a package inside one of these is importable
#: by its bare name. Mirrors the ``pip install -e`` layout in the Makefile.
IMPORT_ROOTS = (
    REPO / "apps" / "api",
    REPO / "packages" / "knowledge-schema",
    REPO / "services" / "sandbox",
    REPO / "services" / "ingestion",
)

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".next", ".mypy_cache", ".pytest_cache"}


class ModuleIndex:
    """Every module in the repo, mapped to the top-level names it binds.

    Keyed by ``(import root, dotted name)`` rather than by dotted name alone, and
    that is not incidental bookkeeping. Three files in this repo spell
    ``tests.conftest`` (``apps/api``, ``packages/knowledge-schema``,
    ``services/ingestion``) and two spell ``tests``. Under one flat map the last
    root indexed wins and the earlier files are not skipped-with-a-warning, they are
    simply absent, which produced exactly the defect this tool exists to prevent:
    every relative import in ``apps/api/tests`` was resolved against the *ingestion*
    conftest, so names that are defined were reported missing while the API's own
    test package went unverified.

    Per root is also the honest model of Python's own resolution, which walks
    ``sys.path`` entry by entry: a relative import finds the sibling in its own tree,
    not a same-named module under a different install root.
    """

    def __init__(self) -> None:
        #: root -> dotted module name -> set of bound names
        self.names: dict[Path, dict[str, set[str]]] = {}
        #: root -> dotted module name -> source path
        self.paths: dict[Path, dict[str, Path]] = {}
        #: root -> dotted package names that exist (so ``from x import submodule`` resolves)
        self.packages: dict[Path, set[str]] = {}

    def add(self, root: Path, dotted: str, path: Path, tree: ast.Module) -> None:
        self.paths.setdefault(root, {})[dotted] = path
        self.names.setdefault(root, {})[dotted] = bound_names(tree)
        packages = self.packages.setdefault(root, set())
        if path.name == "__init__.py":
            packages.add(dotted)
        parts = dotted.split(".")
        for index in range(1, len(parts)):
            packages.add(".".join(parts[:index]))

    def modules(self) -> list[tuple[Path, str, Path]]:
        """``(root, dotted, path)`` for every module indexed, in file order."""
        found = [
            (root, dotted, path)
            for root, mapping in self.paths.items()
            for dotted, path in mapping.items()
        ]
        return sorted(found, key=lambda item: str(item[2]))

    def module_count(self) -> int:
        return sum(len(mapping) for mapping in self.paths.values())

    def bound(self, root: Path, dotted: str) -> set[str]:
        return self.names.get(root, {}).get(dotted, set())

    def _holders(self, dotted: str, root: Path) -> list[Path]:
        """Roots that contain ``dotted``, the asking module's own root first.

        The cross-root fallback is what lets ``from learnos_schema import Concept``
        resolve from inside ``apps/api``: the editable install in the Makefile puts
        all four roots on ``sys.path``. The own-root priority is what stops
        ``from .conftest import ...`` being answered by a different package's
        conftest, and it is authoritative: if the asking root has the module, no
        other root gets a vote, because Python would not consult one either.
        """
        others = [candidate for candidate in self.paths if candidate != root]
        hits = [
            candidate
            for candidate in ([root, *others] if root in self.paths else others)
            if dotted in self.names.get(candidate, {}) or dotted in self.packages.get(candidate, set())
        ]
        return hits[:1] if hits and hits[0] == root else hits

    def defines(self, dotted: str, name: str, *, root: Path) -> bool:
        for holder in self._holders(dotted, root):
            if name in self.bound(holder, dotted):
                return True
            # ``from package import submodule`` is legal without the submodule being
            # named in ``__init__.py``, so a matching module counts as a definition.
            child = f"{dotted}.{name}"
            if child in self.names.get(holder, {}) or child in self.packages.get(holder, set()):
                return True
        return False

    def known(self, dotted: str, *, root: Path) -> bool:
        return bool(self._holders(dotted, root))

    def collisions(self) -> dict[str, list[Path]]:
        """Dotted names that exist under more than one import root.

        Not an import defect on its own, and deliberately not fatal: nothing here
        imports across test roots. It is reported because it is the reason a single
        root-level ``pytest`` cannot work, and because a future collision between two
        real packages would be a defect that this line is the earliest warning of.
        """
        holders: dict[str, list[Path]] = {}
        for mapping in self.paths.values():
            for dotted, path in mapping.items():
                holders.setdefault(dotted, []).append(path)
        return {dotted: sorted(paths) for dotted, paths in holders.items() if len(paths) > 1}


def bound_names(tree: ast.Module) -> set[str]:
    """Top-level names a module binds.

    Includes conditional and try/except bodies, because a name bound inside
    ``if TYPE_CHECKING:`` or a ``try: import x except ImportError:`` fallback is
    still importable at runtime in at least one branch, and flagging it would
    produce noise rather than findings.
    """
    names: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    names.update(_target_names(target))
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                names.update(_target_names(node.target))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    names.add(alias.asname or alias.name)
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.While)):
                visit(node.body)
                visit(getattr(node, "orelse", []))
                visit(getattr(node, "finalbody", []))
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
    visit(tree.body)
    return names


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out: set[str] = set()
        for element in target.elts:
            out |= _target_names(element)
        return out
    return set()


def dotted_name_for(path: Path, root: Path) -> str | None:
    """Module path -> dotted name, or ``None`` if it is not inside a package."""
    relative = path.relative_to(root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    if not parts:
        return None
    return ".".join(parts)


def source_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return sorted(out)


def build_index(roots: tuple[Path, ...]) -> tuple[ModuleIndex, list[str]]:
    index = ModuleIndex()
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            # Hard error, not a skip. A silently-ignored root is worse than no
            # checker at all: it reports "ok" over a package it never opened.
            # This exact defect shipped once. IMPORT_ROOTS said
            # ``packages/sandbox-runner`` while the package lived at
            # ``services/sandbox``, and every sandbox module went unverified
            # while the tool printed a clean bill of health.
            errors.append(f"{root.relative_to(REPO) if root.is_relative_to(REPO) else root}: import root does not exist")
            continue
        found = source_files(root)
        if not found:
            errors.append(f"{root.relative_to(REPO)}: import root contains no Python files")
            continue
        for path in found:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"{path.relative_to(REPO)}:{exc.lineno}: syntax error: {exc.msg}")
                continue
            dotted = dotted_name_for(path, root)
            if dotted is None:
                continue
            index.add(root, dotted, path, tree)
    return index, errors


def resolve_relative(current: str, node: ast.ImportFrom, is_package: bool) -> str:
    """Absolute module for a relative import.

    ``level`` counts from the current *package*, so a module (not a package) starts
    one segment shallower than its own dotted name.
    """
    parts = current.split(".")
    if not is_package:
        parts = parts[:-1]
    up = node.level - 1
    if up:
        parts = parts[: len(parts) - up] if up <= len(parts) else []
    base = ".".join(parts)
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base


def module_aliases(
    tree: ast.Module, dotted: str, is_package: bool, index: ModuleIndex, root: Path
) -> dict[str, str]:
    """Local alias -> dotted module, for every in-repo module bound by an import.

    Only module bindings are collected. ``from .x import helper`` binds a function
    and is already checked by the import pass; ``from . import x`` and
    ``from .a import b as b_mod`` bind modules whose *attribute* access is what this
    enables checking.
    """
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            target = resolve_relative(dotted, node, is_package) if node.level else (node.module or "")
            if not target or not index.known(target, root=root):
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{target}.{alias.name}"
                if index.known(candidate, root=root):
                    aliases[alias.asname or alias.name] = candidate
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if index.known(alias.name, root=root):
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name
    return aliases


def rebound_names(tree: ast.Module) -> set[str]:
    """Every name assigned or bound as a parameter anywhere in the file.

    Used to suppress module-attribute checks on an alias that is shadowed
    somewhere: ``progress`` may be a module at the top of a file and a local
    variable inside one of its functions, and chasing that would produce noise
    instead of findings.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
    return out


def check(index: ModuleIndex) -> list[str]:
    problems: list[str] = []
    for root, dotted, path in index.modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        is_package = path.name == "__init__.py"
        location = path.relative_to(REPO)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                target = resolve_relative(dotted, node, is_package)
                if not index.known(target, root=root):
                    problems.append(f"{location}:{node.lineno}: relative import resolves to unknown module {target!r}")
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not index.defines(target, alias.name, root=root):
                        problems.append(
                            f"{location}:{node.lineno}: {target} does not define {alias.name!r}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                # Absolute, but possibly into another package in this repo.
                if not index.known(node.module, root=root):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not index.defines(node.module, alias.name, root=root):
                        problems.append(
                            f"{location}:{node.lineno}: {node.module} does not define {alias.name!r}"
                        )

        # ``module.attr`` where ``module`` is an in-repo module. This is the check
        # that catches a service function renamed out from under its callers, and
        # the one worth the false-positive suppression below.
        aliases = module_aliases(tree, dotted, is_package, index, root)
        shadowed = rebound_names(tree) - set(aliases)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
                continue
            target = aliases.get(node.value.id)
            if target is None or node.value.id in shadowed:
                continue
            if not index.defines(target, node.attr, root=root):
                problems.append(f"{location}:{node.lineno}: {target} has no attribute {node.attr!r}")

        # ``__all__`` entries that no longer exist are a public-API lie.
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            defined = index.bound(root, dotted)
            for element in node.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    if element.value not in defined:
                        problems.append(
                            f"{location}:{node.lineno}: __all__ exports {element.value!r} which is not defined here"
                        )
    return problems


def main(argv: list[str]) -> int:
    roots = tuple(Path(arg).resolve() for arg in argv[1:]) or IMPORT_ROOTS
    index, errors = build_index(roots)
    problems = errors + check(index)

    if problems:
        for problem in problems:
            print(problem)
        print(f"\n{len(problems)} problem(s) across {index.module_count()} modules")
        return 1

    print(f"ok: {index.module_count()} modules, every intra-repo import resolves")
    for dotted, paths in sorted(index.collisions().items()):
        where = ", ".join(str(p.relative_to(REPO)) for p in paths)
        print(f"note: {dotted!r} exists under more than one import root ({where}).")
    if index.collisions():
        print("      Resolved per root here, the way sys.path would. It is also why a single")
        print("      root-level `pytest` raises ImportPathMismatchError and `make test` runs")
        print("      one invocation per package.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
