"""LearnOS ingestion pipeline.

Turns internet sources into reviewed candidates for a Subject Package. The stage
order is fixed and each stage is a pure-ish function over the previous stage's
output:

    fetch -> parse -> clean -> chunk -> embed -> extract -> validate -> build

Two boundaries are worth stating up front, because the whole design follows from
them.

**This service is the only component with outbound network access.** The API that
serves learner traffic must never fetch a URL or call an extractor: doing so would
block a request thread for minutes and would put crawl credentials in the process
with the widest attack surface. The two halves communicate through the five
``ingestion_*`` tables, whose DDL the API owns.

**Nothing here publishes.** ``extract`` and ``validate`` write candidates in
``draft``; a human moves them to ``approved`` through the admin API; only then does
``build`` fold them into a package on disk. Approving is not publishing, and
publishing is an offline build step rather than an HTTP call.
"""

from __future__ import annotations

from .config import IngestionSettings, get_settings
from .hashing import chunk_id_for, content_hash, document_id_for, stable_id
from .pipeline import Pipeline, PipelineResult

__all__ = [
    "IngestionSettings",
    "Pipeline",
    "PipelineResult",
    "chunk_id_for",
    "content_hash",
    "document_id_for",
    "get_settings",
    "stable_id",
]

__version__ = "0.1.0"
