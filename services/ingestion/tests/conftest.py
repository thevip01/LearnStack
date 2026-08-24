"""Shared fixtures.

No database. Every test in this suite runs against a fake repository or a pure
function, and that is a deliberate constraint rather than a shortcut: the properties
worth testing here (a document id ignores its body, a code fence never gets split, a
non-permissive licence refuses to fetch) are properties of the algorithms, and
routing them through Postgres would only make the suite slow enough that nobody runs
it before committing.

The one thing a fake repository must not do is drift from the real one. ``FakeRepo``
implements the methods the stages actually call and raises ``AttributeError`` for
anything else by simply not having it, so a stage that starts calling a new method
fails loudly here rather than passing against a permissive mock.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# Importable without `pip install -e`, for the same reason the schema suite does this:
# `make test` runs `pytest services/ingestion/tests` from the repo root, and without
# these inserts it fails at import on a fresh clone rather than running. The inserts
# are no-ops once the editable installs exist. `apps/api` is on the list because
# `storage/repository.py` imports `learnos_api.models.ingestion`: the ingestion
# service reuses the API's tables rather than declaring its own copies of them.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
for _path in (
    SERVICE_ROOT,
    REPO_ROOT / "packages" / "knowledge-schema",
    REPO_ROOT / "apps" / "api",
):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402  (after the path inserts, on purpose)
from learnos_schema.ingestion import Chunk, ExtractionCandidate, ParsedDocument, SourceSpec  # noqa: E402

from learnos_ingestion.config import IngestionSettings  # noqa: E402
from learnos_ingestion.hashing import chunk_id_for, content_hash  # noqa: E402


@dataclass
class FakeCandidateRow:
    """Stands in for ``IngestionCandidate``. Only the columns the code reads."""

    id: str
    subject_id: str
    target: str
    payload: dict
    chunk_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5
    issues: list[dict] = field(default_factory=list)
    duplicate_of: str | None = None
    provenance: dict = field(default_factory=dict)
    status: str = "draft"


class FakeRepo:
    """In-memory stand-in for ``IngestionRepository``."""

    def __init__(self) -> None:
        self.sources: list[SourceSpec] = []
        self.hashes: dict[str, dict[str, str]] = {}
        self.etags: dict[str, dict[str, str]] = {}
        self.chunks: list[Chunk] = []
        self.candidates: list[FakeCandidateRow] = []
        self.parsed: list[ParsedDocument] = []
        self.published: list[str] = []
        self.stages: list = []
        self.deleted: list[str] = []

    async def sources_for(self, subject_id, source_ids=None):  # noqa: ANN001
        return [
            spec
            for spec in self.sources
            if spec.subject_id == subject_id and (not source_ids or spec.id in source_ids)
        ]

    async def known_document_hashes(self, source_id):  # noqa: ANN001
        return dict(self.hashes.get(source_id, {}))

    async def known_etags(self, source_id):  # noqa: ANN001
        return dict(self.etags.get(source_id, {}))

    async def upsert_raw(self, document):  # noqa: ANN001
        self.hashes.setdefault(document.source_id, {})[document.id] = document.content_hash

    async def attach_parsed(self, parsed):  # noqa: ANN001
        self.parsed.append(parsed)

    async def documents_for(self, source_id, document_ids=None):  # noqa: ANN001, ARG002
        return []

    async def delete_documents(self, document_ids):  # noqa: ANN001
        ids = list(document_ids)
        self.deleted.extend(ids)
        return len(ids)

    async def replace_chunks(self, document_id, chunks):  # noqa: ANN001
        self.chunks = [chunk for chunk in self.chunks if chunk.document_id != document_id]
        self.chunks.extend(chunks)
        return len(chunks)

    async def chunks_for(self, subject_id, *, source_ids=None):  # noqa: ANN001
        return [
            chunk
            for chunk in self.chunks
            if chunk.subject_id == subject_id and (not source_ids or chunk.source_id in source_ids)
        ]

    async def mark_embedded(self, chunk_ids, model):  # noqa: ANN001, ARG002
        return len(list(chunk_ids))

    async def existing_candidate_ids(self, subject_id, target):  # noqa: ANN001
        return [
            row.payload["id"]
            for row in self.candidates
            if row.subject_id == subject_id and row.target == target and isinstance(row.payload.get("id"), str)
        ]

    async def upsert_candidate(self, candidate: ExtractionCandidate) -> bool:
        for row in self.candidates:
            if row.id == candidate.id:
                return False
        self.candidates.append(
            FakeCandidateRow(
                id=candidate.id,
                subject_id=candidate.subject_id,
                target=str(candidate.target),
                payload=candidate.payload,
                chunk_ids=list(candidate.chunk_ids),
                confidence=candidate.confidence,
                issues=[issue.model_dump(mode="json") for issue in candidate.issues],
            )
        )
        return True

    async def candidates_citing(self, chunk_ids):  # noqa: ANN001
        wanted = set(chunk_ids)
        return [row for row in self.candidates if wanted.intersection(row.chunk_ids)]

    async def approved_candidates(self, subject_id):  # noqa: ANN001
        return [row for row in self.candidates if row.subject_id == subject_id and row.status == "approved"]

    async def mark_published(self, candidate_ids):  # noqa: ANN001
        self.published.extend(candidate_ids)
        return len(list(candidate_ids))

    async def mark_source_run(self, source_id):  # noqa: ANN001, ARG002
        return None

    async def create_run(self, run):  # noqa: ANN001, ARG002
        return None

    async def append_stage(self, run_id, report):  # noqa: ANN001, ARG002
        self.stages.append(report)

    async def finish_run(self, run_id, status):  # noqa: ANN001, ARG002
        return None


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def settings(tmp_path: Path) -> IngestionSettings:
    return IngestionSettings(
        ENV="development",
        DATABASE_URL="postgresql+asyncpg://x:x@localhost/x",
        SUBJECTS_DIR=str(tmp_path / "subjects"),
        INGESTION_STORAGE_DIR=str(tmp_path / "var"),
    )


def make_chunk(
    text: str,
    *,
    ordinal: int = 0,
    document_id: str = "doc.test.1",
    source_id: str = "test.source",
    subject_id: str = "programming.python",
    heading_path: list[str] | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id_for(document_id, ordinal, text),
        document_id=document_id,
        source_id=source_id,
        subject_id=subject_id,
        ordinal=ordinal,
        text=text,
        heading_path=heading_path or [],
        token_estimate=len(text) // 4,
        content_hash=content_hash(text),
    )
