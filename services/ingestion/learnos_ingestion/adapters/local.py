"""Local-filesystem adapter.

The most important adapter in the repo, despite being the least interesting. It is
what lets the entire pipeline run with no network at all: point a source at a
directory of Markdown and every downstream stage behaves exactly as it would after
a crawl. That means the fetch-through-build path is testable and demoable offline,
and it means the hand-authored Python subject package can be re-derived through the
real pipeline rather than being a special case that bypasses it.

It is also the adapter used by the ``local`` source in ``sources.json``, so the
provenance trail for hand-authored content points at real files rather than at
nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from learnos_schema.ingestion import AdapterKind, RawDocument

from ..hashing import content_hash, document_id_for
from .base import FetchRefused, SourceAdapter

if TYPE_CHECKING:  # pragma: no cover
    import httpx

#: Extensions worth reading. Everything else in a directory is ignored rather than
#: read-and-discarded, because a repo checkout contains binaries and a .git dir.
READABLE_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".html", ".htm", ".json", ".yaml", ".yml"})

MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".rst": "text/x-rst",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


class LocalAdapter(SourceAdapter):
    """Walk a directory (or read a single file) under ``entrypoint``."""

    kind = AdapterKind.LOCAL

    def __init__(self, spec, *, root: Path | None = None, **kwargs) -> None:  # noqa: ANN001
        super().__init__(spec, **kwargs)
        #: Sandbox for path resolution. ``entrypoint`` is resolved *under* this and
        #: must stay under it, so a source spec cannot be authored to read /etc.
        #: Subject packages are editable content: treating a path in one as
        #: trusted would make "add a source" equivalent to "read any file".
        self.root = (root or Path.cwd()).resolve()

    def _resolved(self) -> Path:
        candidate = (self.root / self.spec.entrypoint).resolve()
        if not candidate.is_relative_to(self.root):
            raise FetchRefused(
                f"source {self.spec.id!r} entrypoint {self.spec.entrypoint!r} resolves outside "
                f"the permitted root {self.root}"
            )
        return candidate

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        target = self._resolved()
        if target.is_file():
            yield str(target)
            return
        if not target.is_dir():
            raise FetchRefused(f"source {self.spec.id!r} entrypoint {target} does not exist")
        # Sorted so a run is reproducible. Filesystem order is not stable across
        # machines, and an unstable order makes two runs produce chunk ordinals that
        # disagree, which in turn makes the diff report spurious changes.
        for path in sorted(target.rglob("*")):
            if path.is_file() and path.suffix.lower() in READABLE_SUFFIXES:
                if any(part.startswith(".") for part in path.parts):
                    continue
                yield str(path)

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        path = Path(locator)
        try:
            body = path.read_bytes()
        except OSError:
            return None
        stat = path.stat()
        relative = path.relative_to(self.root) if path.is_relative_to(self.root) else path
        return RawDocument(
            id=document_id_for(self.spec.id, str(relative)),
            source_id=self.spec.id,
            url=None,
            path=str(relative),
            media_type=MEDIA_TYPES.get(path.suffix.lower(), "text/plain"),
            http_status=None,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            content_hash=content_hash(body),
            byte_size=len(body),
        )

    def permits(self, locator: str) -> bool:
        # Local paths are matched against the repo-relative form, so a deny pattern
        # written as "tests/" behaves the same whether the checkout is at /app or
        # /home/someone/src.
        path = Path(locator)
        if path.is_relative_to(self.root):
            locator = str(path.relative_to(self.root))
        return super().permits(locator)
