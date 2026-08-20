"""Liveness and readiness.

The distinction matters to an orchestrator: ``/healthz`` answers "is this process
alive", so it must not touch Postgres, Redis or Docker — a health check that fails
because the database is slow gets the container killed for something a restart
cannot fix. ``/readyz`` answers "should traffic come here", so it checks
everything and returns 503 when a dependency is down.

Neither route is under ``/api/v1``: they are infrastructure, not product surface,
and their paths are baked into compose healthchecks.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from .. import cache
from ..db import ping_database
from ..schemas.health import HealthOut, ReadyOut
from ..version import VERSION
from .deps import ExecutionDep

router = APIRouter(tags=["health"], include_in_schema=True)


@router.get("/healthz", response_model=HealthOut)
async def healthz() -> HealthOut:
    return HealthOut(version=VERSION)


@router.get("/readyz", response_model=ReadyOut)
async def readyz(response: Response, execution: ExecutionDep) -> ReadyOut:
    postgres = await ping_database()
    redis = await cache.ping_redis()
    sandbox = await execution.probe()

    # Postgres is the only hard dependency. Redis down means slower responses,
    # not wrong ones, and no sandbox means practice degrades to the non-executing
    # kinds — neither is a reason to pull the whole instance out of rotation.
    ready = postgres
    if not ready or not redis or sandbox == "unavailable":
        response.status_code = 503

    return ReadyOut(
        status="ready" if (postgres and redis and sandbox != "unavailable") else "degraded",
        postgres=postgres,
        redis=redis,
        sandbox=sandbox,
    )
