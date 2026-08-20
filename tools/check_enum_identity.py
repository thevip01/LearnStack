#!/usr/bin/env python3
"""Fail the build on ``x is SomeEnum.MEMBER``.

Why this exists: ``SchemaModel`` sets ``use_enum_values=True``, so a pydantic field
declared as an enum holds a plain ``str`` once validated. Every enum in this repo
subclasses ``str``, so ``==``, dict lookups, f-strings and ``match`` all keep working
against the coerced value and nothing looks wrong. Only ``is`` stops matching, and it
stops matching *silently* and *always*, which turns a guard into a no-op.

That is not a hypothetical. Four checks in ``learnos_schema`` were dead this way at
once: the hint penalty was charged on the concept dimension, ``weighted_score``
returned 0 for every successful run with no test cases, the "a published manifest
needs a content hash" validator never fired, and ``load_all_packages(...,
skip_unpublished=True)`` returned an empty catalogue. None of them raised, and the
type checker was happy with all four. A reviewer cannot reliably catch this class of
bug by reading, so it gets a machine check instead.

The rule is deliberately absolute: compare enum members with ``==``, never ``is``.
The one automatic exception is a comparison inside the enum class's own body, where
``self`` genuinely is a member. There is no pragma to opt out, because every site
that wanted one turned out to be a place where ``==`` was equally correct and more
robust.

Matching is by class name, collected across the whole tree. Two unrelated enums with
the same name would make this over-eager, which is an acceptable trade for a check
that needs no imports and no installed dependencies.

Usage:
    python3 tools/check_enum_identity.py [root ...]

Exit code 1 if any identity comparison against an enum member is found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DEFAULT_ROOTS = (REPO / "packages", REPO / "apps" / "api", REPO / "services")

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".next", ".mypy_cache", ".pytest_cache"}

#: Test suites are the one place the pattern is meaningful: ``test_enum_coercion.py``
#: asserts that a model field ``is not`` its enum member, which is the fact this whole
#: check exists because of. Flagging that assertion would mean deleting the
#: documentation of the bug in order to satisfy the guard against it.
SKIP_DIRS_ANY = {"tests"}

ENUM_BASES = {"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag", "ReprEnum"}


def python_files(roots: tuple[Path, ...]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            parts = set(path.parts)
            if not (parts & SKIP_DIRS) and not (parts & SKIP_DIRS_ANY):
                found.append(path)
    return found


def _base_name(node: ast.expr) -> str:
    """``Enum`` from either ``Enum`` or ``enum.Enum``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def collect_enum_classes(trees: dict[Path, ast.Module]) -> set[str]:
    names: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(_base_name(b) in ENUM_BASES for b in node.bases):
                names.add(node.name)
    return names


def _member_of(node: ast.expr, enums: set[str]) -> str | None:
    """``"MasteryDimension.CONCEPT"`` if this expression is an enum member reference."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in enums
        and node.attr.isupper()
    ):
        return f"{node.value.id}.{node.attr}"
    return None


def enclosing_enum(tree: ast.Module, target: ast.AST, enums: set[str]) -> str | None:
    """Name of the enum class whose body contains ``target``, if any.

    A method on the enum receives a real member as ``self``, so identity there is
    sound. Walking down from the module is cheap enough at this repo's size and
    avoids threading a parent pointer through every visit.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in enums:
            for descendant in ast.walk(node):
                if descendant is target:
                    return node.name
    return None


def check_file(path: Path, tree: ast.Module, enums: set[str]) -> list[str]:
    problems: list[str] = []
    location = path.relative_to(REPO)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op, right in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.Is, ast.IsNot)):
                continue
            for side, other in ((node.left, right), (right, node.left)):
                member = _member_of(side, enums)
                if member is None:
                    continue
                if _member_of(other, enums) is not None:
                    # Both sides are members written out literally, which is sound
                    # (and pointless, but not this check's business).
                    continue
                if enclosing_enum(tree, node, enums):
                    continue
                operator = "is not" if isinstance(op, ast.IsNot) else "is"
                problems.append(
                    f"{location}:{node.lineno}: `{operator} {member}` never matches a value "
                    f"read off a model field; use `{'!=' if isinstance(op, ast.IsNot) else '=='}` instead"
                )
                break
    return problems


def main(argv: list[str]) -> int:
    roots = tuple(Path(arg).resolve() for arg in argv[1:]) or DEFAULT_ROOTS
    trees: dict[Path, ast.Module] = {}
    problems: list[str] = []

    for path in python_files(roots):
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(REPO)}:{exc.lineno}: cannot parse: {exc.msg}")

    enums = collect_enum_classes(trees)
    for path, tree in trees.items():
        problems.extend(check_file(path, tree, enums))

    if problems:
        for problem in problems:
            print(problem)
        print(f"\n{len(problems)} identity comparison(s) against an enum member")
        return 1

    print(f"ok: {len(trees)} modules, {len(enums)} enums, no identity comparisons against a member")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
