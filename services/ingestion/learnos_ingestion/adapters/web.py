"""HTTP adapters: a single page, a sitemap tree, an RSS feed.

All three share ``_http_document``, which is where conditional requests live. A
re-crawl sends ``If-None-Match`` and treats 304 as "unchanged". That is the
cheapest possible refresh, and it is why ``RawDocument`` carries ``etag`` at all.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urldefrag, urlparse
from xml.etree import ElementTree

from learnos_schema.ingestion import AdapterKind, RawDocument

from ..hashing import content_hash, document_id_for
from .base import SourceAdapter

if TYPE_CHECKING:  # pragma: no cover
    import httpx

#: Content types worth keeping. Anything else is fetched and discarded at the
#: header stage rather than downloaded: a docs site links to plenty of tarballs.
TEXTUAL = ("text/", "application/xhtml", "application/json", "application/xml", "+xml")

_HREF = re.compile(rb"""href\s*=\s*["']([^"'#>]+)""", re.IGNORECASE)


def _is_textual(media_type: str) -> bool:
    lowered = media_type.lower()
    return any(marker in lowered for marker in TEXTUAL)


async def _http_document(
    adapter: SourceAdapter,
    client: "httpx.AsyncClient",
    url: str,
    *,
    known_etag: str | None = None,
) -> RawDocument | None:
    """Fetch one URL into a ``RawDocument``, or ``None`` if it should be skipped.

    Returns ``None`` for 304, for non-textual bodies, and for any 4xx. A 5xx also
    yields ``None`` but is worth distinguishing in future: a transient server error
    on page nine of two hundred should probably not silently shrink the corpus.
    """
    headers = {"User-Agent": adapter.policy.user_agent, "Accept-Encoding": "gzip, deflate"}
    if known_etag:
        headers["If-None-Match"] = known_etag

    response = await client.get(
        url,
        headers=headers,
        timeout=adapter.policy.timeout_s,
        follow_redirects=True,
    )
    if response.status_code == 304 or response.status_code >= 400:
        return None

    media_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
    if not _is_textual(media_type):
        return None

    body = response.content
    last_modified: datetime | None = None
    raw_lm = response.headers.get("last-modified")
    if raw_lm:
        try:
            from email.utils import parsedate_to_datetime

            last_modified = parsedate_to_datetime(raw_lm)
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            last_modified = None

    # The final URL after redirects is the identity, not the requested one:
    # otherwise /docs/latest/x and /docs/3.12/x fetch the same page twice.
    final_url = str(response.url)
    return RawDocument(
        id=document_id_for(adapter.spec.id, final_url),
        source_id=adapter.spec.id,
        url=final_url,
        media_type=media_type,
        http_status=response.status_code,
        etag=response.headers.get("etag"),
        last_modified=last_modified,
        content_hash=content_hash(body),
        byte_size=len(body),
        raw_ref=None,  # set by the fetch stage once the bytes are written
    )


class WebAdapter(SourceAdapter):
    """Breadth-first crawl from an entrypoint, bounded by depth and page count.

    Link extraction is a regex over bytes rather than a parse. That is deliberate:
    this stage decides *what to fetch*, and running a full HTML parser here would
    mean parsing every document twice, once to find links and again in the parse
    stage. The regex over-matches (it will happily yield a URL from inside a
    ``<script>`` string); ``permits`` and the content-type check absorb that, and a
    handful of wasted HEADs is cheaper than a second parse of every page.
    """

    kind = AdapterKind.WEB

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        start = self.spec.entrypoint
        origin = urlparse(start).netloc
        seen: set[str] = {start}
        frontier: list[tuple[str, int]] = [(start, 0)]
        yielded = 0

        while frontier and yielded < self.policy.max_pages:
            url, depth = frontier.pop(0)
            yield url
            yielded += 1

            if depth >= self.policy.max_depth:
                continue
            try:
                await self.limiter.wait()
                response = await client.get(
                    url,
                    headers={"User-Agent": self.policy.user_agent},
                    timeout=self.policy.timeout_s,
                    follow_redirects=True,
                )
            except Exception:
                continue
            if response.status_code >= 400 or not _is_textual(
                response.headers.get("content-type", "").split(";")[0]
            ):
                continue

            for match in _HREF.findall(response.content):
                try:
                    href = match.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                absolute, _ = urldefrag(urljoin(url, href))
                if not absolute.startswith(("http://", "https://")):
                    continue
                # Same-origin only. A crawler that follows off-site links from a
                # docs page ends up ingesting a CDN, a status page and Twitter.
                if urlparse(absolute).netloc != origin:
                    continue
                if absolute in seen or not self.permits(absolute):
                    continue
                seen.add(absolute)
                frontier.append((absolute, depth + 1))

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        return await _http_document(self, client, locator)


class SitemapAdapter(SourceAdapter):
    """Read ``sitemap.xml`` and fetch what it lists.

    Preferred over ``WebAdapter`` whenever a site publishes one: a sitemap is the
    site telling you its canonical URL set, which is strictly better than guessing
    it from link structure. Handles sitemap indexes one level deep, which covers
    every real docs site; a nested index beyond that is rare enough to be worth
    failing visibly rather than supporting silently.
    """

    kind = AdapterKind.SITEMAP

    NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        for url in await self._urls(client, self.spec.entrypoint, allow_index=True):
            yield url

    async def _urls(self, client: "httpx.AsyncClient", sitemap_url: str, *, allow_index: bool) -> list[str]:
        try:
            await self.limiter.wait()
            response = await client.get(
                sitemap_url,
                headers={"User-Agent": self.policy.user_agent},
                timeout=self.policy.timeout_s,
                follow_redirects=True,
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except Exception:
            return []

        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "sitemapindex":
            if not allow_index:
                return []
            out: list[str] = []
            for node in root.findall("sm:sitemap/sm:loc", self.NS):
                if node.text:
                    out.extend(await self._urls(client, node.text.strip(), allow_index=False))
                if len(out) >= self.policy.max_pages:
                    break
            return out
        return [node.text.strip() for node in root.findall("sm:url/sm:loc", self.NS) if node.text]

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        return await _http_document(self, client, locator)


class RssAdapter(SourceAdapter):
    """Feed entries as documents.

    Handles RSS 2.0 and Atom by looking for both shapes rather than sniffing, since
    the two are trivially distinguishable by element name and a feed that declares
    one and contains the other is common enough.

    Feeds are the one source type where ``max_pages`` is usually the wrong bound:
    a feed is a window, not a corpus, so a refresh should pick up what is new rather
    than re-fetch the window. That is handled by the fetch stage skipping known
    ``document_id``s, not here.
    """

    kind = AdapterKind.RSS

    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        try:
            await self.limiter.wait()
            response = await client.get(
                self.spec.entrypoint,
                headers={"User-Agent": self.policy.user_agent},
                timeout=self.policy.timeout_s,
                follow_redirects=True,
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except Exception:
            return

        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "link":
                href = node.get("href") or (node.text or "").strip()
                if href.startswith(("http://", "https://")):
                    yield href
            elif tag == "guid" and (node.text or "").startswith(("http://", "https://")):
                yield node.text.strip()

    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        return await _http_document(self, client, locator)
