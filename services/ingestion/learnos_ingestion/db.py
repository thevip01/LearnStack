"""Database engine for the ingestion process.

Separate from ``learnos_api.db`` for the same reason the settings are separate: that
module builds its engine from ``learnos_api.config``, which refuses to construct
without a JWT secret and a Docker socket path. This process needs neither and should
not be able to read either.

The engine is created per command rather than per process. Ingestion is a CLI (one
crawl, one build, one exit), so a module-level pool would exist only to be torn down
seconds later, and a pool that outlives a ``KeyboardInterrupt`` mid-crawl leaves
connections open against a database an operator is about to inspect.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import IngestionSettings


@asynccontextmanager
async def session_scope(settings: IngestionSettings) -> AsyncIterator[AsyncSession]:
    """One session, one engine, disposed on exit.

    ``expire_on_commit=False`` because the pipeline commits between stages and then
    keeps reading the objects it just wrote. With expiry on, every attribute access
    after a stage boundary would emit a lazy refresh inside a sync attribute access,
    which under asyncio raises ``MissingGreenlet`` rather than doing anything useful.

    ``pool_size=1``: every stage shares this one session, and a larger pool would
    imply concurrency the pipeline deliberately does not have (see ``run_fetch``,
    which goes sequential on writes for exactly this reason).
    """
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
