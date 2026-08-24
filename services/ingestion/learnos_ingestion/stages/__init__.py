"""Pipeline stages, in order.

``fetch -> parse -> clean -> chunk -> embed -> extract -> validate -> build``

Each stage is a module-level ``run_*`` coroutine taking the previous stage's output
and returning ``(result, StageReport)``. The report is the operator-facing half and
is persisted incrementally by the pipeline, so a run that dies in ``fetch`` still
shows how far it got.

``clean`` has no separate pass (it runs inside ``parse``, because you cannot find a
heading path without having already decided the nav sidebar is not content), but it
reports separately, since the kept-bytes ratio is the best early warning that a
source changed its template.
"""

from __future__ import annotations

from .build import BuildResult, build_package, next_version, run_build
from .chunk import chunk_document, run_chunk, run_embed
from .extract import run_extract, run_validate, validate_candidate
from .fetch import FetchOutcome, fetch_source, run_fetch
from .parse import ParseResult, clean_report, clean_text, parse_document, run_parse

__all__ = [
    "BuildResult",
    "FetchOutcome",
    "ParseResult",
    "build_package",
    "chunk_document",
    "clean_report",
    "clean_text",
    "fetch_source",
    "next_version",
    "parse_document",
    "run_build",
    "run_chunk",
    "run_embed",
    "run_extract",
    "run_fetch",
    "run_parse",
    "run_validate",
    "validate_candidate",
]
