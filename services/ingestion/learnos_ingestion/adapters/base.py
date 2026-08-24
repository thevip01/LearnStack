"""The adapter contract.

An adapter answers one question: given a ``SourceSpec``, what artefacts exist and
what are their bytes? It returns ``RawDocument`` objects and never parses, cleans
or chunks. Keeping the boundary this narrow is what lets a PDF source and a GitHub
source share every downstream stage.

Two rules live here rather than in each adapter, because "every adapter remembered
to check" is not a security property:

**Licensing is checked before the first byte moves.** ``FetchPolicy.license_ack``
must be set for any source that is not obviously permissive. A platform that
republishes documentation as learning content is making a licensing claim on every
page it ingests, and the moment to fail that check is before the crawl, not during
review of nine hundred candidates.

**robots.txt is honoured by the base class.** An adapter can loosen politeness only
by declaring it in the source's own policy, which is a reviewable diff in
``sources.json`` rather than a line of code nobody reads.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from learnos_schema.ingestion import AdapterKind, FetchPolicy, RawDocument, SourceSpec

if TYPE_CHECKING:  # pragma: no cover
    import httpx

#: Licences permissive enough that ingesting the text needs no explicit sign-off.
#: Anything absent from this set requires ``FetchPolicy.license_ack``. Kept as an
#: allowlist rather than a denylist: the failure mode of a missing entry is an
#: operator adding one line, and the failure mode of a missing denylist entry is
#: shipping someone's copyrighted book as a lesson.
PERMISSIVE_LICENSES = frozenset(
    {
        "cc0",
        "cc0-1.0",
        "cc-by",
        "cc-by-4.0",
        "cc-by-3.0",
        "cc-by-sa",
        "cc-by-sa-4.0",
        "public-domain",
        "psf-2.0",
        "apache-2.0",
        "mit",
        "bsd-2-clause",
        "bsd-3-clause",
        "unlicense",
        "first-party",
    }
)


class FetchRefused(Exception):
    """Raised when policy forbids a fetch that was requested.

    A distinct exception rather than a logged warning and an empty result, because
    "the source yielded nothing" and "we were not allowed to look" must not be
    indistinguishable in a stage report.
    """


class AdapterUnavailable(Exception):
    """The adapter cannot run here: missing optional dependency, or a stub."""


def license_gate(spec: SourceSpec) -> None:
    """Refuse the fetch unless the licence is permissive or acknowledged.

    ``is_first_party`` passes because content the operator wrote needs no
    acknowledgement from the operator.
    """
    if spec.is_first_party:
        return
    declared = (spec.license or "").strip().lower()
    if declared in PERMISSIVE_LICENSES:
        return
    if spec.policy.license_ack:
        return
    raise FetchRefused(
        f"source {spec.id!r} declares license {spec.license!r}, which is not in the permissive allowlist, "
        f"and policy.license_ack is unset. Set license_ack to the reviewed basis for ingesting it "
        f"(e.g. 'reviewed 2026-08: docs licensed CC-BY-SA, attribution retained in SourceRef')."
    )


@dataclass
class RateLimiter:
    """Per-source politeness, enforced by wall clock.

    A token bucket would be more elegant and would also permit a burst, which is
    the one thing a crawler must not do to someone else's docs site. This sleeps to
    maintain a strict minimum interval instead.
    """

    rps: float
    _last: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def wait(self) -> None:
        interval = 1.0 / self.rps
        async with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            self._last = time.monotonic()


class RobotsCache:
    """robots.txt per origin, fetched once per run.

    Failure to fetch robots.txt is treated as *allowed*. That is the conventional
    reading (an absent robots.txt means no restrictions), but it is worth being
    explicit that a 500 from the robots endpoint is also treated this way, because
    the alternative is a docs site with a flaky robots handler silently producing
    empty crawls that look like a content bug.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, RobotFileParser | None] = {}

    async def allows(self, client: "httpx.AsyncClient", url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return True
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = await self._load(client, origin)
        parser = self._parsers[origin]
        if parser is None:
            return True
        return parser.can_fetch(user_agent, url)

    async def _load(self, client: "httpx.AsyncClient", origin: str) -> RobotFileParser | None:
        try:
            response = await client.get(f"{origin}/robots.txt", timeout=10.0)
        except Exception:
            return None
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser


class SourceAdapter(ABC):
    """Base for every adapter.

    Subclasses implement ``discover`` and ``fetch_one``. The template method
    ``run`` is what enforces licensing, robots, rate limiting and page caps, so a
    new adapter gets all four by existing.
    """

    kind: AdapterKind

    def __init__(self, spec: SourceSpec, *, robots: RobotsCache | None = None) -> None:
        self.spec = spec
        self.policy: FetchPolicy = spec.policy
        self.robots = robots or RobotsCache()
        self.limiter = RateLimiter(rps=self.policy.rate_limit_rps)

    # -- subclass surface ---------------------------------------------------

    @abstractmethod
    async def discover(self, client: "httpx.AsyncClient") -> AsyncIterator[str]:
        """Yield locators (URLs or paths) this source contains.

        Yielding lazily matters: a sitemap with forty thousand entries should not be
        materialised to apply a ``max_pages`` of two hundred.
        """
        raise NotImplementedError

    @abstractmethod
    async def fetch_one(self, client: "httpx.AsyncClient", locator: str) -> RawDocument | None:
        """Fetch a single locator, or ``None`` if it should be skipped."""
        raise NotImplementedError

    # -- template -----------------------------------------------------------

    async def run(self, client: "httpx.AsyncClient") -> AsyncIterator[RawDocument]:
        """Discover, gate, and fetch: the only entry point the fetch stage uses."""
        license_gate(self.spec)
        fetched = 0
        async for locator in self.discover(client):
            if fetched >= self.policy.max_pages:
                break
            if not self.permits(locator):
                continue
            if self.policy.respect_robots and not await self.robots.allows(client, locator, self.policy.user_agent):
                continue
            await self.limiter.wait()
            document = await self.fetch_one(client, locator)
            if document is None:
                continue
            fetched += 1
            yield document

    def permits(self, locator: str) -> bool:
        """Apply the source's allow/deny patterns.

        Deny wins over allow. An allowlist that is empty means "everything not
        denied", because requiring an explicit allow pattern on every source would
        make the common case (crawl this docs tree) verbose enough that people would
        skip the deny patterns too.
        """
        import re

        for pattern in self.policy.deny_patterns:
            if re.search(pattern, locator):
                return False
        if not self.policy.allow_patterns:
            return True
        return any(re.search(pattern, locator) for pattern in self.policy.allow_patterns)
