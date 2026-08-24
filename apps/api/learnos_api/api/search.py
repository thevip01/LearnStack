"""Search and compare.

Both are auth-optional and both read only the registry and the search index, so
neither knows who is asking. That is deliberate: personalising search results by
mastery sounds helpful and in practice hides the concept a learner was looking for
because the ranker decided they were not ready for it.

Compare resolves ids across every loaded subject, which is what makes
``Concept.analogues`` work as a cross-subject bridge: "a Python decorator is to a
function what an AWS ALB listener rule is to a request" is only expressible if the
comparison is not scoped to one package.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..errors import BadRequest, NotFound
from ..modules.knowledge import compare as compare_mod
from ..modules.knowledge import search as search_mod
from ..schemas.concept import CompareOut
from ..schemas.search import SearchOut
from .deps import RegistryDep, SessionDep

router = APIRouter(tags=["search"])

#: More than this and the comparison table stops being readable on any screen.
MAX_COMPARE_IDS = 4


@router.get("/search", response_model=SearchOut)
async def search(
    session: SessionDep,
    registry: RegistryDep,
    q: str = Query(min_length=1, max_length=400),
    subject_id: str | None = Query(default=None),
    kind: str | None = Query(default=None, pattern="^(concept|practice|project|skill|subject)$"),
    limit: int = Query(20, ge=1, le=100),
    hybrid: bool = Query(True, description="Set false to force the lexical ranker."),
) -> SearchOut:
    if subject_id is not None:
        # Resolve so a typo'd filter is a 404 rather than zero results, which is
        # indistinguishable from "nothing matched" and much harder to debug.
        registry.get(subject_id)
    return await search_mod.search(
        session, q, subject_id=subject_id, kind=kind, limit=limit, hybrid=hybrid
    )


@router.get("/compare", response_model=CompareOut)
async def compare(
    registry: RegistryDep,
    ids: str = Query(min_length=1, description="Comma-separated concept ids, in the order to show them."),
) -> CompareOut:
    wanted = [part.strip() for part in ids.split(",") if part.strip()]
    if not wanted:
        raise BadRequest("ids must contain at least one concept id")
    if len(wanted) > MAX_COMPARE_IDS:
        raise BadRequest(
            f"compare accepts at most {MAX_COMPARE_IDS} concepts",
            {"received": len(wanted), "limit": MAX_COMPARE_IDS},
        )

    found, missing = compare_mod.resolve(list(registry.iter_packages()), wanted)
    if missing:
        raise NotFound(
            "unknown concept id" + ("s" if len(missing) > 1 else ""),
            {"unknown_ids": missing},
        )
    return compare_mod.build(found)
