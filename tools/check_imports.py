#!/usr/bin/env python3
"""Resolve every intra-repo import against what the target module really defines.

Why this exists: the repo's third-party dependencies cannot always be installed
(air-gapped checkouts, CI without a package index), and without them ``mypy`` and
even ``import learnos_api`` are unavailable. But the defects that actually ship in
a Python codebase this size are overwhelmingly *name* defects — a function renamed
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

#: Directories that are import roots — a package inside one of these is importable
#: by its bare name. Mirrors the ``pip install -e`` layout in the Makefile.
IMPORT_ROOTS = (
    REPO / "apps" / "api",
    REPO / "packages" / "knowledge-schema",
    REPO / "services" / "sandbox",
    REPO / "services" / "ingestion",
)

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".next", ".mypy_cache", ".pytest_cache"}


class ModuleIndex:
    """Every module in the repo, mapped to the top-level names it binds."""

    def __init__(self) -> None:
        #: dotted module name -> set of bound names
        self.names: dict[str, set[str]] = {}
        #: dotted module name -> source path
        self.paths: dict[str, Path] = {}
        #: dotted package names that exist (so ``from x import submodule`` resolves)
        self.packages: set[str] = set()

    def add(self, dotted: str, path: Path, tree: ast.Module) -> None:
        self.paths[dotted] = path
        self.names[dotted] = bound_names(tree)
        if path.name == "__init__.py":
            self.packages.add(dotted)
        parts = dotted.split(".")
        for index in range(1, len(parts)):
            self.packages.add(".".join(parts[:index]))

    def defines(self, dotted: str, name: str) -> bool:
        if name in self.names.get(dotted, ()):
            return True
        # ``from package import submodule`` is legal without the submodule being
        # named in ``__init__.py``, so a matching module counts as a definition.
        return f"{dotted}.{name}" in self.names or f"{dotted}.{name}" in self.packages

    def known(self, dotted: str) -> bool:
        return dotted in self.names or dotted in self.packages


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
            # This exact defect shipped once — IMPORT_ROOTS said
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
            index.add(dotted, path, tree)
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


def module_aliases(tree: ast.Module, dotted: str, is_package: bool, index: ModuleIndex) -> dict[str, str]:
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
            if not target or not index.known(target):
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{target}.{alias.name}"
                if index.known(candidate):
                    aliases[alias.asname or alias.name] = candidate
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if index.known(alias.name):
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name
    return aliases


def rebound_names(tree: ast.Module) -> set[str]:
    """Every name assigned or bound as a parameter anywhere in the file.

    Used to suppress module-attribute checks on an alias that is shadowed
    somewhere — ``progress`` may be a module at the top of a file and a local
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
    for dotted, path in sorted(index.paths.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        is_package = path.name == "__init__.py"
        location = path.relative_to(REPO)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                target = resolve_relative(dotted, node, is_package)
                if not index.known(target):
                    problems.append(f"{location}:{node.lineno}: relative import resolves to unknown module {target!r}")
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not index.defines(target, alias.name):
                        problems.append(
                            f"{location}:{node.lineno}: {target} does not define {alias.name!r}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                # Absolute, but possibly into another package in this repo.
                if not index.known(node.module):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not index.defines(node.module, alias.name):
                        problems.append(
                            f"{location}:{node.lineno}: {node.module} does not define {alias.name!r}"
                        )

        # ``module.attr`` where ``module`` is an in-repo module. This is the check
        # that catches a service function renamed out from under its callers, and
        # the one worth the false-positive suppression below.
        aliases = module_aliases(tree, dotted, is_package, index)
        shadowed = rebound_names(tree) - set(aliases)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
                continue
            target = aliases.get(node.value.id)
            if target is None or node.value.id in shadowed:
                continue
            if not index.defines(target, node.attr):
                problems.append(f"{location}:{node.lineno}: {target} has no attribute {node.attr!r}")

        # ``__all__`` entries that no longer exist are a public-API lie.
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            defined = index.names[dotted]
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
        print(f"\n{len(problems)} problem(s) across {len(index.paths)} modules")
        return 1

    print(f"ok: {len(index.paths)} modules, every intra-repo import resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
