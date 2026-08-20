"""Structured-source adapters: GitHub repositories, OpenAPI specs, PDFs.

These three are grouped because they share a property that separates them from web
and local sources: the artefact has *known structure*, so the adapter can be much
more selective about what it fetches. A GitHub source pulls the docs tree and
skips ``node_modules``; an OpenAPI source is one document that happens to describe
hundreds of operations; a PDF is one document with pages.

``PdfAdapter`` is a real adapter with a deliberately deferred parse: it fetches
bytes like anything else and lets the parse stage decide it cannot read them. That
keeps "we could not fetch it" and "we fetched it and cannot read it" as different
failures, which matters when a source silently starts serving a login page.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from learnos_schema.ingestion import AdapterKind, RawDocument

from ..hashing import content_hash, document_id_for
from .base import AdapterUnavailable, SourceAdapter
from .web import _http_document, _is_textual

if TYPE_CHECKING:  # pragma: no cover
    import httpx

#: Paths inside a repository that are never learning content. Checked as path
#: prefixes and directory names, not as a regex, so ``docs/node_modules`` is caught
#: while a file legitimately named ``vendor-guide.md`` is not.
REPO_SKIP_DIRS = frozenset(
    {".git", ".github", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv", "target"}
)

#: Extensions worth pulling out of a repo. Source code is included: a repository
#: source is often the *best* explanation of a library's real behaviour, and the
#: extract stage can turn a well-commented module into a concept.
REPO_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".py", ".ts", ".tsx", ".go", ".rs", ".java", ".sql"})


class GithubAdapter(SourceAdapter):
    """Fetch a repository's text files through the GitHub REST API.

    Uses the git tree API in one call rather than walking ``contents`` recursively,
    which would be one request per directory and would exhaust an unauthenticated
    rate limit on any real repo.

    ``entrypoint`` is an ``owner/repo`` slug, optionally ``owner/repo@ref``.
    Unauthenticated by default: 60 requests/hour is enough for one tree call plus a
    small file set, and requiring a token to ingest public documentation would make
    the common case need a secret.
    """

    kind = AdapterKind.GITHUB
    API = "https://api.github.com"

    def _slug(self) -> tuple[str, str, str]:
        raw = self.spec.entrypoint.strip().removeprefix("https://github.com/").strip("/")
        ref = "HEAD"
        if "@" in raw:
            raw, ref = raw.rsplit("@", 1)
        parts = raw.split("/")
        if len(parts) < 2:
            raise AdapterUnavailable(
                f"source {self.spec.id!r} entrypoint {self.spec.entrypoint!r} is not an owner/repo slug"
            )
        return parts[0], parts[1], ref

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        owner, repo, ref = self._slug()
        url = f"{self.API}/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
        await self.limiter.wait()
        response = await client.get(
            url,
            headers={"User-Agent": self.policy.user_agent, "Accept": "application/vnd.github+json"},
            timeout=self.policy.timeout_s,
        )
        if response.status_code >= 400:
            return
        tree = response.json().get("tree", [])
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = entry.get("path", "")
            parts = path.split("/")
            if any(part in REPO_SKIP_DIRS for part in parts):
                continue
            if not any(path.endswith(suffix) for suffix in REPO_SUFFIXES):
                continue
            # raw.githubusercontent, not the API's blob endpoint: the API returns
            # base64 inside JSON and counts against the same rate limit, while raw
            # is a plain CDN fetch.
            yield f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        return await _http_document(self, client, locator)


class OpenApiAdapter(SourceAdapter):
    """One spec document, fetched whole.

    Does not expand ``$ref`` or split by operation. That is the parse stage's job:
    an adapter that emitted one ``RawDocument`` per operation would be inventing
    documents that have no independent existence at the source, and a re-fetch
    would then have to diff a synthetic document set rather than a real one.
    """

    kind = AdapterKind.OPENAPI

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        yield self.spec.entrypoint

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        if not locator.startswith(("http://", "https://")):
            from pathlib import Path

            path = Path(locator)
            if not path.is_file():
                return None
            body = path.read_bytes()
            media_type = "application/json" if path.suffix == ".json" else "application/yaml"
            return RawDocument(
                id=document_id_for(self.spec.id, str(path)),
                source_id=self.spec.id,
                path=str(path),
                media_type=media_type,
                content_hash=content_hash(body),
                byte_size=len(body),
            )

        document = await _http_document(self, client, locator)
        if document is None:
            return None
        # A spec endpoint that starts returning HTML is almost always an auth wall
        # or a rewritten SPA route. Failing here beats parsing a login page into
        # nine hundred "concepts".
        if "html" in document.media_type:
            raise AdapterUnavailable(
                f"source {self.spec.id!r} expected an OpenAPI document at {locator} "
                f"but received {document.media_type}; check whether it now requires auth"
            )
        return document


class PdfAdapter(SourceAdapter):
    """Fetch PDF bytes. Text extraction happens in the parse stage.

    ``max_pages`` on a PDF source bounds *documents*, not pages within a document,
    which is worth knowing when a source is a single 900-page standard.
    """

    kind = AdapterKind.PDF

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        entry = self.spec.entrypoint
        if entry.lower().endswith(".pdf") or entry.startswith(("http://", "https://")):
            yield entry
            return
        from pathlib import Path

        root = Path(entry)
        if root.is_dir():
            for path in sorted(root.rglob("*.pdf")):
                yield str(path)

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        if not locator.startswith(("http://", "https://")):
            from pathlib import Path

            path = Path(locator)
            if not path.is_file():
                return None
            body = path.read_bytes()
            return RawDocument(
                id=document_id_for(self.spec.id, str(path)),
                source_id=self.spec.id,
                path=str(path),
                media_type="application/pdf",
                content_hash=content_hash(body),
                byte_size=len(body),
            )

        headers = {"User-Agent": self.policy.user_agent}
        response = await client.get(
            locator, headers=headers, timeout=self.policy.timeout_s, follow_redirects=True
        )
        if response.status_code >= 400:
            return None
        media_type = response.headers.get("content-type", "application/pdf").split(";")[0].strip()
        # _is_textual is inverted here on purpose: this is the one adapter that
        # *wants* a binary body, so a textual response means the URL is wrong.
        if _is_textual(media_type) and "pdf" not in media_type:
            return None
        body = response.content
        return RawDocument(
            id=document_id_for(self.spec.id, str(response.url)),
            source_id=self.spec.id,
            url=str(response.url),
            media_type="application/pdf",
            http_status=response.status_code,
            etag=response.headers.get("etag"),
            content_hash=content_hash(body),
            byte_size=len(body),
        )


def spec_summary(payload: dict) -> str:
    """Render an OpenAPI document as prose the extract stage can read.

    Lives here rather than in the parse stage because it is the only piece of
    OpenAPI knowledge in the codebase and splitting it across two modules would
    mean two places to update when a version of the spec changes shape.
    """
    lines: list[str] = []
    info = payload.get("info", {})
    if isinstance(info, dict):
        title = info.get("title")
        if title:
            lines.append(f"# {title}")
        if info.get("description"):
            lines.append(str(info["description"]))

    paths = payload.get("paths", {})
    if isinstance(paths, dict):
        for path, operations in sorted(paths.items()):
            if not isinstance(operations, dict):
                continue
            for method, operation in sorted(operations.items()):
                if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                    continue
                summary = operation.get("summary") or operation.get("operationId") or ""
                lines.append(f"## {method.upper()} {path}\n{summary}")
                if operation.get("description"):
                    lines.append(str(operation["description"]))
    return "\n\n".join(lines)


def parse_spec(body: bytes) -> dict:
    """JSON first, then YAML. Returns ``{}`` rather than raising on garbage."""
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        pass
    try:
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(body)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
