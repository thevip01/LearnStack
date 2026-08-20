"""Compare mode: two or more concepts, side by side, on the same facets.

This is the feature that makes the analogue edge worth authoring. "What is the AWS
equivalent of a GCP load balancer" is a question every practitioner asks, and the
honest answer is a table, not a paragraph.

The facet list is fixed and generic, derived from ``Concept`` fields rather than
from anything subject-specific. That constraint is what lets compare mode work for
``python.decorator`` vs ``python.context_manager`` on the day it ships for
``aws.alb`` vs ``gcp.lb``, with no code change. A facet with nothing to say for any
of the concepts is dropped rather than rendered as a row of dashes.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from learnos_schema import Concept, SubjectPackage

from ...schemas.concept import CompareOut, CompareRowOut

#: Cap on how many list items a cell shows before it is truncated. A comparison
#: table with eight bullets per cell is not a comparison, it is two documents.
CELL_ITEM_LIMIT = 4


def _bullets(items: Iterable[str]) -> str | None:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return None
    shown = values[:CELL_ITEM_LIMIT]
    suffix = f" (+{len(values) - len(shown)} more)" if len(values) > len(shown) else ""
    return "\n".join(f"- {value}" for value in shown) + suffix


#: ``(facet label, extractor)``. Order is the row order in the rendered table.
FACETS: list[tuple[str, Callable[[Concept], str | None]]] = [
    ("Definition", lambda c: c.definition or None),
    ("Purpose", lambda c: c.purpose or None),
    ("Category", lambda c: c.category or None),
    ("Made of", lambda c: _bullets(f"**{comp.name}** — {comp.role}" for comp in c.components)),
    ("Best practices", lambda c: _bullets(c.best_practices)),
    ("Anti-patterns", lambda c: _bullets(c.anti_patterns)),
    ("In production", lambda c: _bullets(c.production_considerations)),
    ("Common errors", lambda c: _bullets(f"{err.error} → {err.fix}" for err in c.common_errors)),
    ("Prerequisites", lambda c: _bullets(c.prerequisites)),
    ("Time to learn", lambda c: f"{c.estimated_minutes} min"),
]


def resolve(
    packages: Sequence[SubjectPackage],
    ids: Sequence[str],
) -> tuple[list[Concept], list[str]]:
    """Find the requested concepts across every loaded package.

    Cross-package lookup is the point: an analogue's whole value is that it points
    into another subject. Returns ``(found, missing)`` so the route can report the
    ids it could not resolve instead of silently comparing fewer things than asked.
    """
    found: list[Concept] = []
    missing: list[str] = []
    for concept_id in ids:
        match = next((pkg.concepts[concept_id] for pkg in packages if concept_id in pkg.concepts), None)
        if match is None:
            missing.append(concept_id)
        else:
            found.append(match)
    return found, missing


def build(concepts: Sequence[Concept]) -> CompareOut:
    rows: list[CompareRowOut] = []
    for label, extract in FACETS:
        values: dict[str, str | None] = {}
        for concept in concepts:
            try:
                values[concept.id] = extract(concept)
            except Exception:  # pragma: no cover - a malformed cell must not 500 the table
                values[concept.id] = None
        if any(value for value in values.values()):
            rows.append(CompareRowOut(facet=label, values=values))
    return CompareOut(ids=[concept.id for concept in concepts], concepts=list(concepts), rows=rows)


def suggested_pairs(package: SubjectPackage, concept_id: str) -> list[str]:
    """What this concept is worth comparing against.

    Authored analogues first — they are the deliberate cross-subject links — then
    same-category siblings, which is a decent heuristic for "these two get confused
    with each other".
    """
    concept = package.concepts.get(concept_id)
    if concept is None:
        return []
    suggestions = list(concept.analogues)
    for other in package.concepts.values():
        if other.id == concept_id or other.id in suggestions:
            continue
        if other.category == concept.category:
            suggestions.append(other.id)
    return suggestions[:8]
