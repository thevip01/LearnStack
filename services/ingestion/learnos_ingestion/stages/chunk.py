"""Chunk and embed.

Chunking splits on structure first and length second. A chunk that begins mid-
sentence is a chunk that cannot be cited, and citation is the entire point: every
concept the extractor produces carries a ``SourceRef`` pointing at the chunk it came
from, and an admin following that link has to land on something readable.

The embed stage is a stub by design — see ``run_embed``.
"""

from __future__ import annotations

import re

import structlog
from learnos_schema.ingestion import Chunk, IngestionStage, ParsedDocument, StageReport

from ..hashing import chunk_id_for, content_hash, token_estimate

log = structlog.get_logger(__name__)

#: Markdown ATX heading. The parse stage normalises HTML headings into this form
#: precisely so one splitter handles every source type.
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

#: Paragraph boundary. Used as the fallback split when a section is over budget.
_PARAGRAPH = re.compile(r"\n\s*\n")

#: Fenced code. Never split across chunks — see ``_split_section``.
_FENCE = re.compile(r"```.*?```", re.DOTALL)


def _sections(text: str) -> list[tuple[list[str], str]]:
    """Split on headings, returning ``(heading_path, body)`` pairs.

    The heading path is cumulative, so a chunk from under "## Timeouts" inside
    "# Health checks" carries both. That path is what the UI shows as a breadcrumb
    on a citation, and it is what makes a chunk locatable in the original page.
    """
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [([], text)]

    out: list[tuple[list[str], str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        out.append(([], preamble))

    #: level -> heading text, for building the cumulative path
    stack: dict[int, str] = {}
    for index, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        stack = {depth: value for depth, value in stack.items() if depth < level}
        stack[level] = heading
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            out.append(([stack[depth] for depth in sorted(stack)], body))
    return out


def _protect_fences(body: str) -> tuple[str, dict[str, str]]:
    """Replace fenced code with opaque placeholders.

    A code fence split across two chunks produces two chunks of broken code, and a
    practice task generated from either is unrunnable. Protecting them means a
    section containing one enormous example stays whole and simply exceeds the
    target — the right trade, since an oversized chunk is merely inefficient while a
    bisected code sample is wrong.
    """
    placeholders: dict[str, str] = {}

    def swap(match: re.Match[str]) -> str:
        key = f"\x00FENCE{len(placeholders)}\x00"
        placeholders[key] = match.group(0)
        return key

    return _FENCE.sub(swap, body), placeholders


def _restore_fences(text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _split_section(body: str, target: int, overlap: int) -> list[str]:
    """Split one section into pieces of roughly ``target`` tokens."""
    if token_estimate(body) <= target:
        return [body]

    protected, placeholders = _protect_fences(body)
    paragraphs = [part.strip() for part in _PARAGRAPH.split(protected) if part.strip()]

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        tokens = token_estimate(paragraph)
        if current and current_tokens + tokens > target:
            pieces.append("\n\n".join(current))
            # Carry the tail of the previous piece forward. Overlap exists so a
            # statement that straddles a boundary is retrievable from both sides;
            # without it, the sentence explaining why a timeout matters ends up in
            # neither chunk's searchable text.
            carried: list[str] = []
            carried_tokens = 0
            for previous in reversed(current):
                previous_tokens = token_estimate(previous)
                if carried_tokens + previous_tokens > overlap:
                    break
                carried.insert(0, previous)
                carried_tokens += previous_tokens
            current = carried
            current_tokens = carried_tokens
        current.append(paragraph)
        current_tokens += tokens

    if current:
        pieces.append("\n\n".join(current))

    return [_restore_fences(piece, placeholders) for piece in pieces]


def chunk_document(
    parsed: ParsedDocument,
    *,
    subject_id: str,
    target_tokens: int = 1200,
    overlap_tokens: int = 120,
) -> list[Chunk]:
    """Split one parsed document into retrieval units."""
    chunks: list[Chunk] = []
    ordinal = 0

    for heading_path, body in _sections(parsed.text):
        for piece in _split_section(body, target_tokens, overlap_tokens):
            text = piece.strip()
            if len(text) < 80:
                # Too small to teach anything and too small to cite usefully. These
                # are section stubs — "See also", a lone image caption — and they
                # dilute retrieval by matching queries they cannot answer.
                continue
            # The heading path is prepended to the chunk text, not just stored
            # alongside it. Search runs over the text, and a chunk about retry
            # behaviour that never repeats the word "retry" because it sat under a
            # "## Retries" heading is a chunk that is unfindable by the query it
            # answers.
            prefixed = f"{' > '.join(heading_path)}\n\n{text}" if heading_path else text
            chunks.append(
                Chunk(
                    id=chunk_id_for(parsed.document_id, ordinal, text),
                    document_id=parsed.document_id,
                    source_id=parsed.source_id,
                    subject_id=subject_id,
                    ordinal=ordinal,
                    text=prefixed,
                    heading_path=heading_path,
                    token_estimate=token_estimate(prefixed),
                    content_hash=content_hash(prefixed),
                )
            )
            ordinal += 1

    return chunks


async def run_chunk(
    parsed_documents: list[ParsedDocument],
    *,
    subject_id: str,
    repo,  # IngestionRepository
    target_tokens: int = 1200,
    overlap_tokens: int = 120,
    dry_run: bool = True,
) -> tuple[list[Chunk], StageReport]:
    report = StageReport(stage=IngestionStage.CHUNK, items_in=len(parsed_documents))
    all_chunks: list[Chunk] = []

    for parsed in parsed_documents:
        chunks = chunk_document(
            parsed, subject_id=subject_id, target_tokens=target_tokens, overlap_tokens=overlap_tokens
        )
        if not chunks:
            report.skipped += 1
            report.messages.append(f"{parsed.document_id}: produced no chunks above the minimum length")
            continue
        all_chunks.extend(chunks)
        if not dry_run:
            await repo.replace_chunks(parsed.document_id, chunks)

    report.items_out = len(all_chunks)
    log.info("chunk.done", documents=len(parsed_documents), chunks=len(all_chunks), dry_run=dry_run)
    return all_chunks, report


async def run_embed(
    chunks: list[Chunk],
    *,
    repo,  # IngestionRepository
    model: str | None = None,
    dry_run: bool = True,
) -> StageReport:
    """Embedding stage — intentionally not wired to a provider.

    Retrieval currently runs on Postgres full-text plus trigram similarity, which is
    what ``knowledge/search.py`` implements. That is genuinely sufficient for a
    corpus this size and for the query shape learners actually produce ("what does
    ECONNRESET mean here"), and it has the large advantage of needing no vector
    store, no embedding budget and no re-embedding on every content refresh.

    The stage exists rather than being deleted because the schema already carries
    ``embedding_model`` and ``embedded_at`` on every chunk, and because the point at
    which full-text stops being enough — cross-lingual retrieval, or "explain this
    like the section on X" — is a content decision rather than a rewrite. When that
    day comes, this function fills those columns and ``search.py`` gains a vector
    branch; nothing else changes.

    With no model configured it marks the chunks as unembedded and reports so,
    rather than silently succeeding.
    """
    report = StageReport(stage=IngestionStage.EMBED, items_in=len(chunks))
    if not model:
        report.skipped = len(chunks)
        report.messages.append(
            "no embedding model configured; retrieval uses Postgres full-text and trigram search. "
            "Set EMBEDDING_MODEL and implement a provider call here to enable vector retrieval."
        )
        return report

    if not dry_run:
        report.items_out = await repo.mark_embedded([chunk.id for chunk in chunks], model)
    else:
        report.items_out = len(chunks)
    report.messages.append(f"marked {report.items_out} chunks as embedded with {model}")
    return report
