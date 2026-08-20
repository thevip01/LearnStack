"""The HTTP surface, assembled.

One aggregating router so that the ``/api/v1`` prefix is written exactly once. A
prefix repeated across nine modules is a prefix that will eventually disagree with
itself, and the frontend's generated client is built from these paths.

Health is deliberately **not** in the aggregate. ``/healthz`` and ``/readyz`` are
infrastructure, not product surface: their paths are baked into compose
healthchecks and would break if a future ``/api/v2`` moved them.

Include order is not arbitrary. ``catalog`` and ``search`` declare fixed paths and
come first; ``subjects``, ``practice`` and ``progress`` own path parameters that
would otherwise swallow a sibling. FastAPI matches in registration order, so this
list is the disambiguation.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import admin, auth, catalog, execution, health, practice, progress, search, subjects

#: Everything the product speaks, under one version prefix.
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(search.router)
api_router.include_router(subjects.router)
api_router.include_router(practice.router)
api_router.include_router(execution.router)
api_router.include_router(progress.router)
api_router.include_router(admin.router)

#: Mounted at the root by the app factory.
health_router = health.router

__all__ = ["api_router", "health_router"]
