"""Async engine, session factory and the ``get_session`` dependency.

One session per request, one transaction per request. The dependency commits on
a clean return and rolls back on any exception, which is what makes the
submission pipeline atomic without every service function having to know about
transaction boundaries.

The engine is created in the app lifespan rather than at import time so that
tests can point the module at SQLite before anything connects.
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .logging import get_logger
from .models.base import Base

log = get_logger(__name__)

__all__ = ["Base", "init_engine", "get_engine", "get_sessionmaker", "get_session", "dispose_engine", "session_scope"]

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create (or replace) the process-wide engine."""
    global _engine, _sessionmaker

    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        # The test path only. SQLite has no server-side pool to size.
        engine = create_async_engine(url, echo=echo, future=True)
    else:
        engine = create_async_engine(
            url,
            echo=echo,
            future=True,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args=connect_args,
        )

    _engine = engine
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("database engine not initialised; call init_engine() in the app lifespan")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("session factory not initialised; call init_engine() in the app lifespan")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. The commit here is the request's transaction boundary."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class session_scope:
    """Context manager for work outside a request (startup, background tasks).

    Background execution runs after the response has been sent and therefore
    after ``get_session`` has closed its session, so it needs its own.
    """

    def __init__(self) -> None:
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self._session = get_sessionmaker()()
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        assert self._session is not None
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def ping_database() -> bool:
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - readyz reports, it does not raise
        log.warning("postgres_ping_failed", error=str(exc))
        return False
