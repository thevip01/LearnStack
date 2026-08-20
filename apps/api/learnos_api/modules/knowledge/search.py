"""Search: indexing on load, hybrid ranking on query.

The index is a projection. It is rebuilt from the packages on every load and is
never a source of truth, which means a bad index is fixed by restarting rather
than by a migration.

Ranking is hybrid where the database supports it and lexical where it does not:

* On Postgres with ``pg_trgm``: weighted ``tsvector`` over the body, a *separate*
  vector over error strings, and trigram similarity on the title. The three are
  combined with fixed weights.
* Anywhere else (SQLite in tests, Postgres without extensions): a token-overlap
  ranker in Python over the same materialised ``search_text`` column.

The fallback is not a stub. A learning platform whose search dies without an
extension installed is a platform that cannot be developed on a laptop, and the
degradation is visible in ``/readyz`` rather than hidden.

The reason ``error_text`` is indexed separately is worth restating: the single
highest-value query on a platform like this is a learner pasting a traceback. That
query has to find the concept whose ``common_errors`` explains it, and if error
strings are folded into the body vector they are outranked by prose that merely
discusses the topic.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

import sqlalchemy as sa
from learnos_schema import SubjectPackage
from sqlalchemy.ext.asyncio import AsyncSession

from ...logging import get_logger
from ...models import ConceptIndex
from ...schemas.search import SearchOut, SearchResultOut
from ..subjects.assemble import enum_value

log = get_logger(__name__)

#: Static per-kind importance. A concept explains; a practice task drills. When
#: both match a query equally well the explanation is the more useful result.
KIND_BOOST = {
    "concept": 1.25,
    "skill": 1.0,
    "practice": 0.9,
    "project": 0.85,
    "subject": 1.1,
}

SNIPPET_LIMIT = 260
_TOKEN_RE = re.compile(r"[a-z0-9_]+")

#: Combination weights for the Postgres ranker. Error matches are weighted highest
#: on purpose: see the module docstring.
W_ERROR = 3.0
W_BODY = 1.0
W_TITLE_SIMILARITY = 1.5


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _snippet(text: str) -> str:
    cleaned = " ".join(str(text).split())
    return cleaned[:SNIPPET_LIMIT]


def _block_text(blocks: Iterable[object]) -> str:
    """Flatten content blocks into plain text for the body vector."""
    parts: list[str] = []
    for block in blocks:
        for field in ("md", "code", "caption", "title", "text"):
            value = getattr(block, field, None)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def rows_for_package(package: SubjectPackage, content_hash: str) -> list[dict[str, object]]:
    """Every indexable entity in a package, as plain dicts ready for insert."""
    subject_id = package.manifest.id
    rows: list[dict[str, object]] = []

    def add(
        *,
        entity_id: str,
        kind: str,
        title: str,
        summary: str = "",
        definition: str = "",
        keywords: Sequence[str] = (),
        body: str = "",
        error_text: str = "",
    ) -> None:
        keyword_text = " ".join(keywords)
        search_text = " ".join(filter(None, [title, title, keyword_text, summary, definition, body]))
        rows.append(
            {
                "entity_id": entity_id,
                "entity_kind": kind,
                "subject_id": subject_id,
                "content_hash": content_hash,
                "title": title[:500],
                "summary": summary,
                "definition": definition,
                "keywords": keyword_text,
                "body_text": body,
                "error_text": error_text,
                "search_text": search_text,
                "snippet": _snippet(summary or definition or body or title),
                "boost": KIND_BOOST.get(kind, 1.0),
            }
        )

    add(
        entity_id=subject_id,
        kind="subject",
        title=package.manifest.title,
        summary=package.manifest.subtitle or "",
        definition=package.manifest.description or "",
        keywords=list(package.manifest.tags),
    )

    for concept in package.concepts.values():
        add(
            entity_id=concept.id,
            kind="concept",
            title=concept.title,
            summary=concept.summary,
            definition=concept.definition,
            keywords=list(concept.keywords) + list(concept.best_practices)[:3],
            body=" ".join(
                filter(
                    None,
                    [
                        concept.purpose,
                        _block_text(concept.body),
                        " ".join(example.title for example in concept.examples),
                    ],
                )
            ),
            # Symptom text only. The cause and fix live in the body; what has to
            # match a pasted traceback is the error as the learner sees it.
            error_text="\n".join(error.error for error in concept.common_errors),
        )

    for task in package.practice.values():
        add(
            entity_id=task.id,
            kind="practice",
            title=task.title,
            summary=_snippet(task.prompt_md),
            keywords=list(task.tags) + [enum_value(task.kind)],
            body=task.prompt_md,
        )

    for project in package.projects.values():
        add(
            entity_id=project.id,
            kind="project",
            title=project.title,
            summary=getattr(project, "summary", "") or _snippet(getattr(project, "brief_md", "")),
            body=getattr(project, "brief_md", ""),
        )

    for skill in package.curriculum.skills:
        add(
            entity_id=skill.id,
            kind="skill",
            title=skill.title,
            summary=getattr(skill, "description", "") or "",
        )

    return rows


async def reindex_subject(
    session: AsyncSession,
    package: SubjectPackage,
    content_hash: str,
) -> int:
    """Replace one subject's index rows. Delete-then-insert, inside the caller's transaction.

    Not an upsert: a concept removed from a package has to vanish from search, and
    reconciling that with an upsert means tracking which ids were seen anyway.
    """
    await session.execute(sa.delete(ConceptIndex).where(ConceptIndex.subject_id == package.manifest.id))
    rows = rows_for_package(package, content_hash)
    if rows:
        await session.execute(sa.insert(ConceptIndex), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Postgres-only DDL
# ---------------------------------------------------------------------------

#: Generated columns and indexes that only exist on Postgres. Applied on startup
#: and each statement guarded, so a database without the extensions simply keeps
#: the lexical fallback.
_PG_DDL = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    """
    ALTER TABLE concept_index
      ADD COLUMN IF NOT EXISTS search_tsv tsvector
      GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(keywords, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(definition, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body_text, '')), 'C')
      ) STORED
    """,
    """
    ALTER TABLE concept_index
      ADD COLUMN IF NOT EXISTS error_tsv tsvector
      GENERATED ALWAYS AS (to_tsvector('english', coalesce(error_text, ''))) STORED
    """,
    "CREATE INDEX IF NOT EXISTS ix_concept_index_search_tsv ON concept_index USING gin (search_tsv)",
    "CREATE INDEX IF NOT EXISTS ix_concept_index_error_tsv ON concept_index USING gin (error_tsv)",
    "CREATE INDEX IF NOT EXISTS ix_concept_index_title_trgm ON concept_index USING gin (title gin_trgm_ops)",
]


async def install_full_text(session: AsyncSession) -> bool:
    """Try to install the Postgres search objects. Returns whether ranking is hybrid.

    Each statement is attempted independently: a managed Postgres that forbids
    ``CREATE EXTENSION`` should still get the tsvector columns, which are the part
    that matters most.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return False
    installed = 0
    for statement in _PG_DDL:
        try:
            await session.execute(sa.text(statement))
            installed += 1
        except Exception as exc:  # pragma: no cover - depends on server privileges
            await session.rollback()
            log.warning("search_ddl_skipped", statement=statement.split("\n")[0].strip()[:60], error=str(exc))
    await session.commit()
    # The two tsvector columns plus their indexes are the minimum for the hybrid
    # ranker; the trigram index only affects typo tolerance.
    return installed >= 3


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

_PG_QUERY = sa.text(
    """
    SELECT entity_id, entity_kind, subject_id, title, snippet, boost,
           ts_rank_body, ts_rank_error, title_sim,
           (:w_body * ts_rank_body + :w_error * ts_rank_error + :w_title * title_sim) * boost AS score
    FROM (
        SELECT entity_id, entity_kind, subject_id, title, snippet, boost,
               ts_rank(search_tsv, q) AS ts_rank_body,
               ts_rank(error_tsv, q) AS ts_rank_error,
               similarity(title, :raw) AS title_sim
        FROM concept_index, websearch_to_tsquery('english', :raw) AS q
        WHERE (:subject_id IS NULL OR subject_id = :subject_id)
          AND (:kind IS NULL OR entity_kind = :kind)
          AND (search_tsv @@ q OR error_tsv @@ q OR title % :raw)
    ) ranked
    ORDER BY score DESC
    LIMIT :limit
    """
)


def _matched_on(*, error_rank: float, title_similarity: float) -> str:
    if error_rank > 0:
        return "error_text"
    if title_similarity >= 0.45:
        return "title"
    return "body"


async def _search_postgres(
    session: AsyncSession,
    query: str,
    *,
    subject_id: str | None,
    kind: str | None,
    limit: int,
) -> list[SearchResultOut]:
    result = await session.execute(
        _PG_QUERY,
        {
            "raw": query,
            "subject_id": subject_id,
            "kind": kind,
            "limit": limit,
            "w_body": W_BODY,
            "w_error": W_ERROR,
            "w_title": W_TITLE_SIMILARITY,
        },
    )
    out: list[SearchResultOut] = []
    for row in result.mappings():
        out.append(
            SearchResultOut(
                id=row["entity_id"],
                kind=row["entity_kind"],
                subject_id=row["subject_id"],
                title=row["title"],
                snippet=row["snippet"],
                score=round(float(row["score"] or 0.0), 5),
                matched_on=_matched_on(
                    error_rank=float(row["ts_rank_error"] or 0.0),
                    title_similarity=float(row["title_sim"] or 0.0),
                ),
            )
        )
    return out


def score_lexically(query_tokens: Sequence[str], row: ConceptIndex) -> tuple[float, str]:
    """Token-overlap ranking, used when the database has no full text search.

    Deliberately simple and deliberately explainable: overlap counted per field,
    each field weighted, multiplied by the row's static boost. It will not beat
    ``ts_rank``, but it returns the right answer for short queries and exact error
    strings, which is what development and tests need.
    """
    if not query_tokens:
        return 0.0, "body"

    title_tokens = set(tokens(row.title))
    keyword_tokens = set(tokens(row.keywords))
    error_tokens = set(tokens(row.error_text))
    body_tokens = set(tokens(row.search_text))
    wanted = set(query_tokens)

    title_hits = len(wanted & title_tokens)
    keyword_hits = len(wanted & keyword_tokens)
    error_hits = len(wanted & error_tokens)
    body_hits = len(wanted & body_tokens)

    # Phrase bonus: the whole query appearing verbatim in the error text is the
    # pasted-traceback case and should dominate.
    phrase = " ".join(query_tokens)
    phrase_bonus = 2.0 if phrase and phrase in row.error_text.lower() else 0.0

    score = (
        2.5 * title_hits / max(len(wanted), 1)
        + 2.0 * keyword_hits / max(len(wanted), 1)
        + W_ERROR * error_hits / max(len(wanted), 1)
        + 1.0 * body_hits / max(len(wanted), 1)
        + phrase_bonus
    ) * float(row.boost or 1.0)

    if error_hits or phrase_bonus:
        matched = "error_text"
    elif title_hits:
        matched = "title"
    elif keyword_hits:
        matched = "keyword"
    else:
        matched = "body"
    return score, matched


async def _search_lexical(
    session: AsyncSession,
    query: str,
    *,
    subject_id: str | None,
    kind: str | None,
    limit: int,
) -> list[SearchResultOut]:
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    stmt = sa.select(ConceptIndex)
    if subject_id:
        stmt = stmt.where(ConceptIndex.subject_id == subject_id)
    if kind:
        stmt = stmt.where(ConceptIndex.entity_kind == kind)
    # Narrow with a LIKE on the longest token before ranking in Python. With a few
    # thousand rows this is fine; it is also exactly the point at which someone
    # should install pg_trgm.
    longest = max(query_tokens, key=len)
    stmt = stmt.where(
        sa.or_(
            ConceptIndex.search_text.ilike(f"%{longest}%"),
            ConceptIndex.error_text.ilike(f"%{longest}%"),
        )
    ).limit(500)

    result = await session.execute(stmt)
    scored: list[tuple[float, str, ConceptIndex]] = []
    for row in result.scalars():
        score, matched = score_lexically(query_tokens, row)
        if score > 0:
            scored.append((score, matched, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    return [
        SearchResultOut(
            id=row.entity_id,
            kind=row.entity_kind,  # type: ignore[arg-type]
            subject_id=row.subject_id,
            title=row.title,
            snippet=row.snippet,
            score=round(score, 5),
            matched_on=matched,  # type: ignore[arg-type]
        )
        for score, matched, row in scored[:limit]
    ]


async def search(
    session: AsyncSession,
    query: str,
    *,
    subject_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    hybrid: bool = True,
) -> SearchOut:
    """Run a search, falling back to lexical ranking if the hybrid query fails.

    The fallback is inside the try/except rather than decided only by dialect: a
    Postgres whose generated columns were not created would otherwise turn every
    search into a 500, and search failing softly is much better than search
    failing loudly.
    """
    cleaned = " ".join(query.split())[:200]
    if not cleaned:
        return SearchOut(query=cleaned, results=[])

    limit = min(max(limit, 1), 50)
    is_pg = session.bind is not None and session.bind.dialect.name == "postgresql"
    if hybrid and is_pg:
        try:
            results = await _search_postgres(session, cleaned, subject_id=subject_id, kind=kind, limit=limit)
            return SearchOut(query=cleaned, results=results)
        except Exception as exc:  # pragma: no cover - depends on installed DDL
            await session.rollback()
            log.warning("search_hybrid_failed", error=str(exc))

    results = await _search_lexical(session, cleaned, subject_id=subject_id, kind=kind, limit=limit)
    return SearchOut(query=cleaned, results=results)
