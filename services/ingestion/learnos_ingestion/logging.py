"""Logging for the ingestion CLI.

Duplicated from the API's version rather than imported, and the duplication is the
point: log lines here go to **stderr**, not stdout. The CLI's stdout is a report an
operator pipes into a file or greps, and structlog's own output interleaved with it
would corrupt exactly the output someone is trying to read.

The API's logger writes to stdout because a container's stdout is what a log
collector scrapes. Both are right for their process.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from .config import IngestionSettings


def configure_logging(settings: IngestionSettings) -> None:
    numeric = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=numeric, force=True)
    # SQLAlchemy echoes every statement at INFO. A crawl of two hundred pages emits
    # thousands, which buries the stage reports that are the actual output.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # httpx logs a line per request at INFO; the fetch stage already reports its own
    # per-source summary, and the per-request stream is only useful when debugging a
    # single adapter.
    logging.getLogger("httpx").setLevel(logging.WARNING if numeric > logging.DEBUG else logging.INFO)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.is_development:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))
    else:
        processors += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def bind_run(run_id: str, subject_id: str) -> None:
    """Bind run identity so every subsequent line carries it.

    A crawl produces log lines from seven modules; without this an operator reading a
    failure has no way to tell which run or which subject it belonged to when two
    runs overlap.
    """
    structlog.contextvars.bind_contextvars(run=run_id, subject=subject_id)
