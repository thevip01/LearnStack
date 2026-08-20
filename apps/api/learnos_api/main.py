"""The app factory.

``create_app()`` rather than a module-level ``app`` so tests can build an instance
with a registry pointed at a fixture directory and a runner that never touches
Docker. Uvicorn gets ``app`` at the bottom, which costs one line and keeps
``uvicorn learnos_api.main:app`` working.

Startup order is load-bearing and worth reading before changing:

1. logging, so everything after it is structured
2. the engine, because the schema step needs it
3. the schema (development only), because the search DDL alters those tables
4. Redis, because the registry mirror writes to it
5. the subject registry, because the search index is built from what loaded
6. the execution probe, because ``/readyz`` reports its answer

The registry is the interesting one. Subject packages are read from disk once, at
startup, and every request is served from the assembled result. That is the whole
reason a subject can be data rather than code: the cost of "the subject is a
directory of JSON" is paid once per process, not once per request.

Failures at startup are asymmetric on purpose. A missing database is fatal — there
is nothing to serve. A missing Docker daemon is not: the platform still teaches,
it just cannot run code, and it says so in ``/readyz``. Refusing to boot because a
sandbox is unavailable would make the theory half of the product unavailable too.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import cache
from .api import api_router, health_router
from .config import Settings, get_settings
from .db import dispose_engine, get_engine, init_engine, session_scope
from .errors import install_error_handlers
from .logging import bind_request_id, clear_request_context, configure_logging, get_logger
from .models.base import Base
from .modules.execution import ExecutionService
from .modules.knowledge import search as search_mod
from .modules.subjects import SubjectRegistry
from .version import VERSION

log = get_logger(__name__)

REQUEST_ID_HEADER = "x-request-id"
VERSION_HEADER = "x-learnos-version"

DESCRIPTION = """
One runtime, many subjects.

A subject is a *package of data* — manifest, curriculum, concepts, practice tasks,
UI layout — not an application. Selecting `Cloud → AWS → Load Balancing` loads a
different package into the same runtime; nothing about the code is AWS-specific.

The loop this API implements: **Source → Structured Knowledge → Subject Package →
Dynamic UI → Interactive Practice → Evaluation → Skill Mastery.**
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    configure_logging(settings.LOG_LEVEL, json_output=not settings.is_development)

    if not settings.is_development:
        problems = settings.insecure_defaults()
        if problems:
            # Refuse rather than warn. A production deployment running on the
            # shipped JWT secret is one where every session token is forgeable,
            # and a log line nobody reads is not a control.
            raise RuntimeError("refusing to start with development defaults outside development: " + "; ".join(problems))

    init_engine(settings.DATABASE_URL, echo=False)

    if settings.AUTO_CREATE_SCHEMA:
        # The vertical-slice path: ``create_all`` so a fresh checkout boots with no
        # migration step. Alembic owns the schema for anything long-lived, which is
        # why this is a flag and not the only path.
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("schema_ensured")

    cache.init_redis(settings.REDIS_URL)

    registry = SubjectRegistry(settings.subjects_path)
    report = await registry.reload()
    await registry.mirror_to_cache()
    app.state.registry = registry
    if report.failed:
        # Loud, but not fatal. One malformed package must not take the catalog down.
        log.error("subject_packages_failed", subjects=[failure.subject_id for failure in report.failed])
    if not report.loaded:
        log.warning("no_subjects_loaded", subjects_dir=str(settings.subjects_path))

    async with session_scope() as session:
        hybrid = await search_mod.install_full_text(session)
        indexed = 0
        for subject in registry.all_subjects():
            indexed += await search_mod.reindex_subject(session, subject.package, subject.content_hash)
    log.info("search_index_built", rows=indexed, hybrid=hybrid)

    execution = ExecutionService(settings, registry=registry)
    state = await execution.probe()
    app.state.execution = execution
    log.info("sandbox_probed", state=state)

    if settings.SEED_DEMO_USER:
        from .seed import seed_demo_user

        async with session_scope() as session:
            await seed_demo_user(session, settings)

    log.info("api_started", version=VERSION, env=settings.ENV, subjects=report.loaded, sandbox=state)
    try:
        yield
    finally:
        await execution.close()
        await cache.close_redis()
        await dispose_engine()
        log.info("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="LearnOS API",
        description=DESCRIPTION,
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    # Credentials are allowed because the session travels as a cookie, and that
    # rules out a wildcard origin — the browser refuses the combination anyway, so
    # a wildcard here would break the web app rather than loosen it.
    #
    # Starlette runs middleware in reverse registration order, so the request-id
    # middleware registered below ends up *outside* this one. That is the order we
    # want: a CORS preflight is still tagged and logged, which is how you diagnose
    # the class of failure where the browser rejects a response the server thinks
    # it sent correctly.
    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, VERSION_HEADER],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001, ANN202
        """Bind a request id for the life of the request, and echo it back.

        An inbound ``x-request-id`` is trusted and reused so a trace survives the
        hop from the web app; that is safe because the value is only ever logged
        and echoed, never used in a query or a path.

        ``clear_request_context`` in the ``finally`` is not optional: structlog's
        contextvars outlive the request otherwise, and under an ASGI server that
        reuses tasks the next request inherits the previous request's id.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        bind_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            clear_request_context()
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[VERSION_HEADER] = VERSION
        return response

    install_error_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
