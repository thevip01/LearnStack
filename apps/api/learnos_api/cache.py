"""Redis cache.

Two rules hold everywhere in this module:

1. The cache is an accelerator, never a source of truth. Every miss and every
   connection failure has to be survivable, so the helpers swallow Redis errors
   and return ``None``. A Redis outage degrades latency, not correctness.
2. Keys are namespaced and versioned. ``learnos:v1:`` prefixes everything, so a
   schema change to a cached payload is a prefix bump rather than a flush.

Subject runtimes are keyed by content hash, which is what makes the cache
self-invalidating: reloading a changed package writes a new key and the old one
expires on its own.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from .logging import get_logger

log = get_logger(__name__)

NAMESPACE = "learnos:v1"

# A loaded subject runtime changes only when its content hash changes, so it can
# be cached for a long time. Progress is recomputed from evidence on write, so
# its TTL is a safety net rather than the invalidation mechanism.
TTL_SUBJECT_RUNTIME = 7 * 24 * 3600
TTL_PROGRESS = 300
TTL_SEARCH = 60
TTL_CATALOG = 600

_client: aioredis.Redis | None = None


def init_redis(url: str) -> aioredis.Redis:
    global _client
    _client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    return _client


def get_redis() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("redis client not initialised; call init_redis() in the app lifespan")
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _client = None


def key(*parts: str) -> str:
    return ":".join((NAMESPACE, *(str(p) for p in parts)))


def subject_runtime_key(subject_id: str, content_hash: str) -> str:
    """The key the architecture doc names: ``subject:{id}:{content_hash}``."""
    return key("subject", subject_id, content_hash)


def progress_key(user_id: str, subject_id: str) -> str:
    return key("progress", user_id, subject_id)


async def get_json(cache_key: str) -> Any | None:
    if _client is None:
        return None
    try:
        raw = await _client.get(cache_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_get_failed", key=cache_key, error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A poisoned value is worse than a miss; drop it and let the caller rebuild.
        log.warning("cache_value_corrupt", key=cache_key)
        await delete(cache_key)
        return None


async def set_json(cache_key: str, value: Any, ttl_s: int) -> None:
    if _client is None:
        return
    try:
        await _client.set(cache_key, json.dumps(value, default=str), ex=ttl_s)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_set_failed", key=cache_key, error=str(exc))


async def delete(*cache_keys: str) -> None:
    if _client is None or not cache_keys:
        return
    try:
        await _client.delete(*cache_keys)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_delete_failed", keys=list(cache_keys), error=str(exc))


async def incr_window(window_key: str, window_s: int) -> int:
    """Fixed-window counter used by the rate limiters.

    Fixed windows allow a 2x burst at a boundary. That is an acceptable trade for
    registration and ad-hoc runs, where the goal is to stop scripted abuse rather
    than to shape traffic precisely. Returns a very large number when Redis is
    unreachable is *not* the behaviour: an outage must not lock everyone out, so
    it returns 0 and the limiter fails open.
    """
    if _client is None:
        return 0
    try:
        pipe = _client.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, window_s)
        result = await pipe.execute()
        return int(result[0])
    except Exception as exc:  # noqa: BLE001
        log.warning("rate_limit_backend_unavailable", key=window_key, error=str(exc))
        return 0


async def ping_redis() -> bool:
    if _client is None:
        return False
    try:
        return bool(await _client.ping())
    except Exception as exc:  # noqa: BLE001
        log.warning("redis_ping_failed", error=str(exc))
        return False
