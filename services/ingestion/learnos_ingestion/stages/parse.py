"""Parse and clean: bytes to text worth chunking.

Parse and clean are one module because the boundary between them is artificial in
practice — you cannot extract a heading path from HTML without having already
decided that the nav sidebar is not content. Splitting them into two passes would
mean either parsing twice or passing a half-cleaned tree between stages.

The stage list keeps both names because ``StageReport`` is what an operator reads,
and "clean removed 60% of the bytes" is a useful thing to see separately from
"parse found 200 documents".

Boilerplate stripping is the part most likely to need tuning per source. It is
deliberately conservative: a selector that removes too much silently deletes
content, and the failure is invisible until a learner reads a concept with a hole
in it. Removing too little only costs some noise in the chunks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog
from learnos_schema.ingestion import IngestionStage, ParsedDocument, StageReport

from ..adapters import parse_spec, spec_summary
from ..hashing import content_hash, stable_id

log = structlog.get_logger(__name__)

#: Elements that are never content on a documentation page.
CHROME_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript", "iframe", "form", "svg")

#: Class/id fragments that mark chrome on the docs generators in wide use
#: (Sphinx, MkDocs, Docusaurus, GitBook, VitePress). Matched as substrings against
#: the class and id attributes.
CHROME_HINTS = (
    "sidebar",
    "navbar",
    "breadcrumb",
    "toc",
    "table-of-contents",
    "pagination",
    "edit-this-page",
    "cookie",
    "banner",
    "announcement",
    "skip-link",
    "search",
    "theme-toggle",
)

#: Runs of three or more blank lines collapse to two. Docs converted from HTML are
#: full of these and they inflate the token estimate without carrying meaning.
_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")
#: Zero-width and non-breaking characters. These break naive string matching in
#: graders and quiz answers, so they are normalised out at the earliest point.
_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")


@dataclass
class ParseResult:
    parsed: ParsedDocument | None
    skipped_reason: str | None = None


def clean_text(text: str) -> str:
    """Whitespace and invisible-character normalisation.

    Deliberately does not touch punctuation, quotes or dashes. Smart quotes in a
    code block are a bug in the source; smart quotes in prose are correct, and this
    function cannot tell the difference. Normalising them here would corrupt code
    samples, which are the one thing in a learning platform that must survive
    byte-exact.
    """
    text = _INVISIBLE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _TRAILING_WS.sub("\n", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def parse_html(body: bytes, *, url: str | None) -> tuple[str, str | None, list[str], list[dict], list[dict], str | None]:
    """HTML to ``(text, title, heading_path, code_blocks, tables, canonical_url)``.

    Code blocks are extracted *before* the text is flattened and are kept verbatim
    with their language hint. This matters more than anything else in the parse
    stage: a code sample that has been through whitespace normalisation is a code
    sample that no longer runs, and the practice tasks generated from it would be
    broken in ways a reviewer would not spot by reading prose.
    """
    from bs4 import BeautifulSoup  # imported lazily so `--help` works without lxml

    soup = BeautifulSoup(body, "lxml")

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        first_h1 = soup.find("h1")
        if first_h1:
            title = first_h1.get_text(strip=True)

    canonical = None
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        canonical = str(link["href"])

    # Code blocks first, while the tree is intact.
    code_blocks: list[dict] = []
    for index, node in enumerate(soup.find_all(("pre", "code"))):
        # A <code> nested in a <pre> is the same block; keep the outer one only.
        if node.name == "code" and node.find_parent("pre") is not None:
            continue
        source = node.get_text()
        if not source.strip():
            continue
        classes = " ".join(node.get("class") or [])
        language = None
        for token in classes.split():
            for prefix in ("language-", "lang-", "highlight-", "sourceCode "):
                if token.startswith(prefix.strip()):
                    language = token[len(prefix.strip()) :].strip("-")
                    break
            if language:
                break
        code_blocks.append({"ordinal": index, "language": language, "source": source})

    tables: list[dict] = []
    for index, node in enumerate(soup.find_all("table")):
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(("th", "td"))]
            for row in node.find_all("tr")
        ]
        rows = [row for row in rows if any(cell for cell in row)]
        if rows:
            tables.append({"ordinal": index, "rows": rows})

    for tag in CHROME_TAGS:
        for node in soup.find_all(tag):
            node.decompose()
    for node in soup.find_all(attrs={"class": True}):
        marker = " ".join(node.get("class") or []).lower()
        if any(hint in marker for hint in CHROME_HINTS):
            node.decompose()
    for node in soup.find_all(attrs={"id": True}):
        marker = str(node.get("id") or "").lower()
        if any(hint in marker for hint in CHROME_HINTS):
            node.decompose()

    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup

    heading_path = [
        node.get_text(" ", strip=True)
        for node in main.find_all(("h1", "h2", "h3"))
        if node.get_text(strip=True)
    ][:12]

    # Headings survive as Markdown so the chunker can split on structure. Without
    # them, a chunk boundary lands mid-explanation and the chunk cites a heading it
    # does not contain.
    for level in range(1, 7):
        for node in main.find_all(f"h{level}"):
            node.replace_with(f"\n\n{'#' * level} {node.get_text(' ', strip=True)}\n\n")

    return clean_text(main.get_text("\n")), title, heading_path, code_blocks, tables, canonical or url


def parse_markdown(text: str) -> tuple[str, str | None, list[str], list[dict]]:
    """Markdown needs no conversion — only heading and fence extraction."""
    lines = text.split("\n")
    title: str | None = None
    heading_path: list[str] = []
    code_blocks: list[dict] = []

    fence: list[str] | None = None
    fence_language: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if fence is None:
                fence = []
                fence_language = stripped[3:].strip() or None
            else:
                code_blocks.append(
                    {"ordinal": len(code_blocks), "language": fence_language, "source": "\n".join(fence)}
                )
                fence = None
                fence_language = None
            continue
        if fence is not None:
            fence.append(line)
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                if title is None:
                    title = heading
                if len(heading_path) < 12:
                    heading_path.append(heading)

    return clean_text(text), title, heading_path, code_blocks


def parse_document(
    *,
    document_id: str,
    source_id: str,
    media_type: str,
    body: bytes,
    url: str | None,
) -> ParseResult:
    """Dispatch on media type. Returns a skip reason rather than raising."""
    lowered = media_type.lower()

    try:
        if "pdf" in lowered:
            # No PDF text extraction wired. A stub that returned empty text would be
            # worse than an explicit skip: the document would look successfully
            # parsed and simply produce no concepts, which is indistinguishable from
            # a PDF that genuinely has no content. Wiring this means adding pypdf
            # and handling the scanned-image case, which needs OCR and a real
            # decision about cost.
            return ParseResult(None, "pdf text extraction not wired; install the pdf extra and enable it")

        if "html" in lowered or "xhtml" in lowered:
            text, title, headings, code_blocks, tables, canonical = parse_html(body, url=url)
        elif "json" in lowered or "yaml" in lowered:
            payload = parse_spec(body)
            if payload.get("openapi") or payload.get("swagger"):
                text = clean_text(spec_summary(payload))
                title = str(payload.get("info", {}).get("title") or "") or None
            else:
                text = clean_text(json.dumps(payload, indent=2) if payload else body.decode("utf-8", "replace"))
                title = None
            headings, code_blocks, tables, canonical = [], [], [], url
        else:
            decoded = body.decode("utf-8", errors="replace")
            text, title, headings, code_blocks = parse_markdown(decoded)
            tables, canonical = [], url
    except Exception as exc:  # noqa: BLE001
        return ParseResult(None, f"{type(exc).__name__}: {exc}")

    if len(text) < 200:
        # Below this a page is a redirect stub, a 404 body or a nav-only index.
        # Letting them through means the extractor spends budget on pages that say
        # nothing, and it means chunks that match a search but teach nothing.
        return ParseResult(None, f"only {len(text)} characters of text after cleaning")

    return ParseResult(
        ParsedDocument(
            id=stable_id(f"parsed.{source_id}", document_id, text),
            document_id=document_id,
            source_id=source_id,
            title=title,
            canonical_url=canonical,
            text=text,
            heading_path=headings,
            code_blocks=code_blocks,
            tables=tables,
            word_count=len(text.split()),
            content_hash=content_hash(text),
        )
    )


async def run_parse(
    documents: list[tuple[str, str, str, bytes, str | None]],
    *,
    repo,  # IngestionRepository — untyped to avoid a circular import
    dry_run: bool = True,
) -> tuple[list[ParsedDocument], StageReport]:
    """Parse every touched document.

    Takes ``(document_id, source_id, media_type, body, url)`` tuples rather than
    ``RawDocument`` objects because the body is not on the model — it lives in the
    object store, and the pipeline is what knows how to pair them.
    """
    report = StageReport(stage=IngestionStage.PARSE, items_in=len(documents))
    out: list[ParsedDocument] = []

    for document_id, source_id, media_type, body, url in documents:
        result = parse_document(
            document_id=document_id, source_id=source_id, media_type=media_type, body=body, url=url
        )
        if result.parsed is None:
            report.skipped += 1
            report.messages.append(f"{document_id}: {result.skipped_reason}")
            continue
        out.append(result.parsed)
        if not dry_run:
            try:
                await repo.attach_parsed(result.parsed)
            except LookupError as exc:
                report.ok = False
                report.messages.append(str(exc))

    report.items_out = len(out)
    log.info("parse.done", parsed=len(out), skipped=report.skipped, dry_run=dry_run)
    return out, report


def clean_report(parsed: list[ParsedDocument], raw_bytes: int) -> StageReport:
    """The clean stage's report.

    Clean has no separate pass — ``clean_text`` runs inside parse — so this
    summarises what that removed. Reported separately because the ratio is the
    single most useful signal that a source's boilerplate selectors are wrong: a
    docs site that suddenly cleans down to 5% of its bytes has changed its template.
    """
    kept = sum(len(document.text.encode("utf-8")) for document in parsed)
    report = StageReport(
        stage=IngestionStage.CLEAN,
        items_in=len(parsed),
        items_out=len(parsed),
    )
    if raw_bytes:
        ratio = kept / raw_bytes
        report.messages.append(f"kept {kept:,} of {raw_bytes:,} bytes ({ratio:.1%}) after boilerplate removal")
        if ratio < 0.05:
            report.ok = False
            report.messages.append(
                "under 5% of bytes survived cleaning, which usually means the source changed template "
                "and CHROME_HINTS is now deleting content — check a parsed document before approving candidates"
            )
    return report
