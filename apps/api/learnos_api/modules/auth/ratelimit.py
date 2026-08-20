"""Rate limiting.

Fixed-window counters in Redis. The limiter **fails open** when Redis is
unreachable: a cache outage taking down registration and code execution for
everyone is a worse failure than briefly losing abuse protection. That trade is
only defensible because these limits protect against scripted abuse rather than
gating anything that costs money per call.
"""

from __future__ import annotations

from dataclasses import dataclass

from ... import cache
from ...errors import RateLimited
from ...logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Limit:
    name: str
    max_calls: int
    window_s: int


# Registration is the cheapest thing to abuse and the most annoying to clean up.
REGISTER_LIMIT = Limit("register", max_calls=5, window_s=3600)
LOGIN_LIMIT = Limit("login", max_calls=20, window_s=900)
# Ad-hoc execution is the only endpoint that costs real CPU.
ADHOC_EXECUTION_LIMIT = Limit("adhoc_exec", max_calls=30, window_s=300)


async def enforce(limit: Limit, identity: str) -> None:
    """Raise ``RateLimited`` when ``identity`` has exceeded ``limit``."""
    window_key = cache.key("rl", limit.name, identity)
    count = await cache.incr_window(window_key, limit.window_s)
    if count > limit.max_calls:
        log.info("rate_limited", limit=limit.name, identity=identity, count=count)
        raise RateLimited(
            f"too many {limit.name.replace('_', ' ')} attempts; try again later",
            retry_after_s=limit.window_s,
            detail={"limit": limit.max_calls, "window_s": limit.window_s},
        )
