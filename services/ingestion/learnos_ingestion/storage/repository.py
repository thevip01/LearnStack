"""Database access for the pipeline.

Talks to the five ``ingestion_*`` tables and nothing else. The API owns their DDL;
this service owns their contents. That split is enforced by convention here rather
than by a database grant, which is the obvious hardening step for a real
deployment: this process has no business being able to write ``users`` or
``mastery_evidence``, and a role that can only touch ``ingestion_*`` would make
that structural instead of aspirational.

Every write is an upsert keyed on the content-derived id, so re-running a stage is
idempotent. That property is what makes the pipeline safe to interrupt: kill it
halfway through a crawl of two hundred pages and the next run re-fetches nothing it
already stored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

from learnos_schema.ingestion import (
    Chunk,
    ExtractionCandidate,
    IngestionRun,
    ParsedDocument,
    RawDocument,
    SourceSpec,
    StageReport,
)
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# The models live in the API package because the API owns the schema and the
# Alembic history. Importing them here rather than redeclaring them is what
# guarantees the two halves cannot disagree about a column name: a duplicated
# declaration drifts the first time someone widens a column and only one side
# knows.
#
# The cost is a package dependency pointing the "wrong" way: the crawler depends on
# the web app. That is paid for in the Dockerfile, which installs learnos-api with
# --no-deps, so this container gets the table declarations without FastAPI, uvicorn
# or the Docker SDK. Worth knowing that `learnos_api.models` imports nothing but
# SQLAlchemy, which is what makes that safe.
#
# The clean version of this is a third package (learnos-db) holding Base and the
# models, depended on by both. Deferred rather than done because it would move
# twelve files and the Alembic env to buy an import direction, and the --no-deps
# install already removes the practical cost.
from learnos_api.models.ingestion import (
    IngestionCandidate as CandidateRow,
    IngestionChunk as ChunkRow,
    IngestionDocument as DocumentRow,
    IngestionRun as RunRow,
    IngestionSource as SourceRow,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionRepository:
    """Thin persistence layer over the ingestion tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- sources ------------------------------------------------------------

    async def sources_for(self, subject_id: str, source_ids: Sequence[str] | None = None) -> list[SourceSpec]:
        """Enabled sources for a subject, highest priority first.

        Priority order is not cosmetic. When two sources describe the same API and
        their extracted concepts collide, the deduplicator keeps the one it saw
        first, so first-party documentation has to be processed before a blog post
        about it, or the blog post wins and nobody notices until a learner reads it.
        """
        query = select(SourceRow).where(SourceRow.subject_id == subject_id, SourceRow.enabled.is_(True))
        if source_ids:
            query = query.where(SourceRow.id.in_(list(source_ids)))
        query = query.order_by(SourceRow.priority.desc(), SourceRow.id.asc())
        rows = (await self.session.execute(query)).scalars().all()
        return [self._source_spec(row) for row in rows]

    @staticmethod
    def _source_spec(row: SourceRow) -> SourceSpec:
        return SourceSpec.model_validate(
            {
                "id": row.id,
                "subject_id": row.subject_id,
                "title": row.title,
                "adapter": row.adapter,
                "source_type": row.source_type,
                "entrypoint": row.entrypoint,
                "priority": row.priority,
                "is_first_party": row.is_first_party,
                "license": row.license,
                "policy": row.policy or {},
                "enabled": row.enabled,
                "last_run_at": row.last_run_at,
                "notes": row.notes,
            }
        )

    async def upsert_source(self, spec: SourceSpec) -> None:
        row = await self.session.get(SourceRow, spec.id)
        payload = spec.model_dump(mode="json", exclude={"id"})
        payload["policy"] = spec.policy.model_dump(mode="json")
        payload["last_run_at"] = spec.last_run_at
        if row is None:
            row = SourceRow(id=spec.id, **payload)
            self.session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)

    async def mark_source_run(self, source_id: str) -> None:
        row = await self.session.get(SourceRow, source_id)
        if row is not None:
            row.last_run_at = _now()

    # -- documents ----------------------------------------------------------

    async def known_document_hashes(self, source_id: str) -> dict[str, str]:
        """``document_id -> content_hash`` for everything already stored.

        This one query is the whole basis of incremental ingestion. The fetch stage
        compares each newly fetched body's hash against this map to classify it as
        added, changed or unchanged, and only the first two go on to parse.
        """
        rows = (
            await self.session.execute(
                select(DocumentRow.id, DocumentRow.content_hash).where(DocumentRow.source_id == source_id)
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    async def known_etags(self, source_id: str) -> dict[str, str]:
        """``url -> etag``, so a refetch can send ``If-None-Match``."""
        rows = (
            await self.session.execute(
                select(DocumentRow.url, DocumentRow.etag).where(
                    DocumentRow.source_id == source_id,
                    DocumentRow.url.is_not(None),
                    DocumentRow.etag.is_not(None),
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    async def upsert_raw(self, document: RawDocument) -> None:
        row = await self.session.get(DocumentRow, document.id)
        values: dict[str, Any] = {
            "source_id": document.source_id,
            "url": document.url,
            "path": document.path,
            "media_type": document.media_type,
            "fetched_at": document.fetched_at,
            "http_status": document.http_status,
            "etag": document.etag,
            "last_modified": document.last_modified,
            "content_hash": document.content_hash,
            "byte_size": document.byte_size,
            "raw_ref": document.raw_ref,
        }
        if row is None:
            self.session.add(DocumentRow(id=document.id, heading_path=[], code_blocks=[], tables=[], **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)

    async def attach_parsed(self, parsed: ParsedDocument) -> None:
        """Write parse output onto the existing document row.

        Deliberately not an insert. ``ingestion_documents`` merges raw and parsed
        because parse output is one-to-one with a fetched document; a missing row
        here means parse ran on something fetch never stored, which is a bug worth
        surfacing rather than papering over with an insert.
        """
        row = await self.session.get(DocumentRow, parsed.document_id)
        if row is None:
            raise LookupError(f"parse produced output for unknown document {parsed.document_id!r}")
        row.parsed_id = parsed.id
        row.title = parsed.title
        row.canonical_url = parsed.canonical_url
        row.text = parsed.text
        row.heading_path = list(parsed.heading_path)
        row.code_blocks = list(parsed.code_blocks)
        row.tables = list(parsed.tables)
        row.published_at = parsed.published_at
        row.language = parsed.language
        row.word_count = parsed.word_count
        row.parsed_content_hash = parsed.content_hash

    async def documents_for(self, source_id: str, document_ids: Sequence[str] | None = None) -> list[DocumentRow]:
        query = select(DocumentRow).where(DocumentRow.source_id == source_id)
        if document_ids is not None:
            if not document_ids:
                return []
            query = query.where(DocumentRow.id.in_(list(document_ids)))
        return list((await self.session.execute(query.order_by(DocumentRow.id))).scalars().all())

    async def delete_documents(self, document_ids: Iterable[str]) -> int:
        ids = list(document_ids)
        if not ids:
            return 0
        # Chunks cascade via the FK, so this deletes their rows too. Raw bodies in
        # the object store are left alone: they are content-addressed and may be
        # shared, and reclaiming them is the explicit `gc` command's job.
        result = await self.session.execute(delete(DocumentRow).where(DocumentRow.id.in_(ids)))
        return int(result.rowcount or 0)

    # -- chunks -------------------------------------------------------------

    async def replace_chunks(self, document_id: str, chunks: Sequence[Chunk]) -> int:
        """Delete-then-insert every chunk for a document.

        Not an upsert. Chunk ids include their text, so an edit that shortens a
        document leaves orphaned high-ordinal chunks that an upsert would never
        touch: they would sit in the index forever, citable and wrong. Replacing
        wholesale costs one extra delete per changed document and removes an entire
        class of stale-content bug.
        """
        await self.session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
        for chunk in chunks:
            self.session.add(
                ChunkRow(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    source_id=chunk.source_id,
                    subject_id=chunk.subject_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    heading_path=list(chunk.heading_path),
                    token_estimate=chunk.token_estimate,
                    content_hash=chunk.content_hash,
                    embedding_model=chunk.embedding_model,
                    embedded_at=chunk.embedded_at,
                )
            )
        return len(chunks)

    async def chunks_for(self, subject_id: str, *, source_ids: Sequence[str] | None = None) -> list[Chunk]:
        query = select(ChunkRow).where(ChunkRow.subject_id == subject_id)
        if source_ids:
            query = query.where(ChunkRow.source_id.in_(list(source_ids)))
        rows = (await self.session.execute(query.order_by(ChunkRow.document_id, ChunkRow.ordinal))).scalars().all()
        return [
            Chunk.model_validate(
                {
                    "id": row.id,
                    "document_id": row.document_id,
                    "source_id": row.source_id,
                    "subject_id": row.subject_id,
                    "ordinal": row.ordinal,
                    "text": row.text,
                    "heading_path": row.heading_path or [],
                    "token_estimate": row.token_estimate,
                    "content_hash": row.content_hash,
                    "embedding_model": row.embedding_model,
                    "embedded_at": row.embedded_at,
                }
            )
            for row in rows
        ]

    async def mark_embedded(self, chunk_ids: Sequence[str], model: str) -> int:
        if not chunk_ids:
            return 0
        rows = (await self.session.execute(select(ChunkRow).where(ChunkRow.id.in_(list(chunk_ids))))).scalars().all()
        stamp = _now()
        for row in rows:
            row.embedding_model = model
            row.embedded_at = stamp
        return len(rows)

    # -- candidates ---------------------------------------------------------

    async def existing_candidate_ids(self, subject_id: str, target: str) -> list[str]:
        """Payload ids already proposed or published, so the extractor can dedupe.

        Reads the id out of the payload rather than the row's primary key: the row
        id is content-derived and meaningless to an extractor, while the payload id
        is the ``Id`` a concept will be published under, which is what a duplicate
        actually collides on.
        """
        rows = (
            await self.session.execute(
                select(CandidateRow.payload).where(
                    CandidateRow.subject_id == subject_id, CandidateRow.target == target
                )
            )
        ).all()
        out: list[str] = []
        for (payload,) in rows:
            if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                out.append(payload["id"])
        return out

    async def upsert_candidate(self, candidate: ExtractionCandidate) -> bool:
        """Write a candidate. Returns ``True`` if it was newly created.

        An existing candidate is **not** overwritten once a human has touched it.
        Re-running extract after a reviewer rejected something must not resurrect
        it, or the review queue becomes impossible to empty: every run would
        re-propose the same rejected candidates forever.
        """
        row = await self.session.get(CandidateRow, candidate.id)
        if row is not None:
            provenance = row.provenance or {}
            if provenance.get("reviewed_by") or row.status not in {"draft", "in_review"}:
                return False
            row.payload = candidate.payload
            row.chunk_ids = list(candidate.chunk_ids)
            row.confidence = candidate.confidence
            row.issues = [issue.model_dump(mode="json") for issue in candidate.issues]
            row.duplicate_of = candidate.duplicate_of
            row.provenance = candidate.provenance.model_dump(mode="json")
            return False

        self.session.add(
            CandidateRow(
                id=candidate.id,
                subject_id=candidate.subject_id,
                target=str(candidate.target),
                payload=candidate.payload,
                chunk_ids=list(candidate.chunk_ids),
                confidence=candidate.confidence,
                issues=[issue.model_dump(mode="json") for issue in candidate.issues],
                duplicate_of=candidate.duplicate_of,
                provenance=candidate.provenance.model_dump(mode="json"),
                status=str(candidate.status),
            )
        )
        return True

    async def approved_candidates(self, subject_id: str) -> list[CandidateRow]:
        """Everything cleared for the build stage.

        ``approved`` only, not ``published``. A published candidate is already in
        the package on disk, and re-folding it in would overwrite whatever hand
        edits an author has made since.
        """
        rows = (
            await self.session.execute(
                select(CandidateRow)
                .where(CandidateRow.subject_id == subject_id, CandidateRow.status == "approved")
                .order_by(CandidateRow.target, CandidateRow.id)
            )
        ).scalars().all()
        return list(rows)

    async def mark_published(self, candidate_ids: Sequence[str]) -> int:
        if not candidate_ids:
            return 0
        rows = (
            await self.session.execute(select(CandidateRow).where(CandidateRow.id.in_(list(candidate_ids))))
        ).scalars().all()
        stamp = _now()
        for row in rows:
            row.status = "published"
            provenance = dict(row.provenance or {})
            provenance["status"] = "published"
            provenance["reviewed_at"] = provenance.get("reviewed_at") or stamp.isoformat()
            row.provenance = provenance
        return len(rows)

    async def candidates_for_review(
        self, subject_id: str, *, status: str = "draft", limit: int = 50
    ) -> list[CandidateRow]:
        """The review queue, worst-confidence last.

        Ordered by confidence descending so a reviewer works down from the candidates
        most likely to be correct. The alternative, surfacing the shakiest first,
        sounds more rigorous and in practice trains reviewers to skim, because the
        first ten things they see are all rejects.
        """
        rows = (
            await self.session.execute(
                select(CandidateRow)
                .where(CandidateRow.subject_id == subject_id, CandidateRow.status == status)
                .order_by(CandidateRow.confidence.desc(), CandidateRow.id)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def set_candidate_status(
        self,
        candidate_ids: Sequence[str],
        status: str,
        *,
        reviewed_by: str,
        note: str | None = None,
    ) -> list[str]:
        """Record a review decision. Returns the ids actually changed.

        ``reviewed_by`` is required rather than optional, and is stamped into
        provenance, because it is what stops a later extract run from resurrecting
        the row: ``upsert_candidate`` refuses to touch anything with a reviewer on
        it. An anonymous approval would be silently undone by the next crawl.

        Approving is **not** publishing. This sets ``approved``; the content reaches
        a learner only when the build stage folds it into a package on disk and an
        admin reloads the registry.
        """
        if not candidate_ids:
            return []
        rows = (
            await self.session.execute(select(CandidateRow).where(CandidateRow.id.in_(list(candidate_ids))))
        ).scalars().all()
        stamp = _now()
        changed: list[str] = []
        for row in rows:
            row.status = status
            provenance = dict(row.provenance or {})
            provenance["status"] = status
            provenance["reviewed_by"] = reviewed_by
            provenance["reviewed_at"] = stamp.isoformat()
            if note:
                provenance["review_note"] = note
            row.provenance = provenance
            changed.append(row.id)
        return changed

    async def live_content_hashes(self) -> set[str]:
        """Every raw-body hash still referenced by a document row.

        Across *all* sources and subjects deliberately. Raw bodies are content
        addressed, so two sources that crawl the same page share one blob; scoping
        this to one subject would let a garbage collection run delete a body the
        other subject still cites.
        """
        rows = (await self.session.execute(select(DocumentRow.content_hash))).all()
        return {row[0] for row in rows if row[0]}

    async def candidates_citing(self, chunk_ids: Sequence[str]) -> list[CandidateRow]:
        """Candidates derived from any of ``chunk_ids``.

        Used by the diff to answer "what does this edit invalidate?". Filtering
        happens in Python because ``chunk_ids`` is a JSON array and the portable
        containment predicate differs between Postgres and SQLite, and the
        candidate count per subject is in the thousands, not the millions.
        """
        if not chunk_ids:
            return []
        wanted = set(chunk_ids)
        rows = (await self.session.execute(select(CandidateRow))).scalars().all()
        return [row for row in rows if wanted.intersection(row.chunk_ids or [])]

    # -- runs ---------------------------------------------------------------

    async def create_run(self, run: IngestionRun) -> None:
        self.session.add(
            RunRow(
                id=run.id,
                subject_id=run.subject_id,
                source_ids=list(run.source_ids),
                target_version=run.target_version,
                dry_run=run.dry_run,
                stages=[report.model_dump(mode="json") for report in run.stages],
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
            )
        )

    async def append_stage(self, run_id: str, report: StageReport) -> None:
        """Persist one stage report as it finishes.

        Written incrementally rather than once at the end so that a run which dies
        during ``fetch`` still shows an operator how far it got. Reassigning the
        list is required, not optional: SQLAlchemy does not track in-place mutation
        of a JSON column, so ``row.stages.append(...)`` would be silently dropped.
        """
        row = await self.session.get(RunRow, run_id)
        if row is None:
            return
        row.stages = [*(row.stages or []), report.model_dump(mode="json")]

    async def finish_run(self, run_id: str, status: str) -> None:
        row = await self.session.get(RunRow, run_id)
        if row is None:
            return
        row.status = status
        row.finished_at = _now()

    # -- diagnostics --------------------------------------------------------

    async def counts(self, subject_id: str) -> dict[str, int]:
        async def count(model, *conditions) -> int:  # noqa: ANN001
            query = select(func.count()).select_from(model)
            for condition in conditions:
                query = query.where(condition)
            return int((await self.session.execute(query)).scalar_one())

        return {
            "sources": await count(SourceRow, SourceRow.subject_id == subject_id),
            "documents": await count(
                DocumentRow,
                DocumentRow.source_id.in_(select(SourceRow.id).where(SourceRow.subject_id == subject_id)),
            ),
            "chunks": await count(ChunkRow, ChunkRow.subject_id == subject_id),
            "candidates": await count(CandidateRow, CandidateRow.subject_id == subject_id),
            "pending_review": await count(
                CandidateRow, CandidateRow.subject_id == subject_id, CandidateRow.status == "draft"
            ),
        }

    async def ping(self) -> bool:
        await self.session.execute(text("SELECT 1"))
        return True
