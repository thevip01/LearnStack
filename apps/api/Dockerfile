# LearnOS API image.
#
# Build context is the repo root, not apps/api, because the API depends on two
# local path packages (packages/knowledge-schema and services/sandbox) that have
# to be installed before it.
#
# Two-stage: the builder gets a compiler toolchain so anything without a wheel
# can build, and the runtime stage gets none of it. That is worth the extra lines
# because this container has the Docker socket mounted in development, so
# shrinking what a compromise inside it can reach is not academic.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

# Everything lands in one prefix so the runtime stage copies a single directory
# rather than reassembling site-packages.
ENV VENV=/opt/venv
RUN python -m venv $VENV
ENV PATH="$VENV/bin:$PATH"

WORKDIR /src

# Dependency metadata first, sources second: editing a route must not invalidate
# the layer that took three minutes to install.
COPY packages/knowledge-schema/pyproject.toml packages/knowledge-schema/
COPY services/sandbox/pyproject.toml services/sandbox/
COPY apps/api/pyproject.toml apps/api/

# Minimal package bodies so the three projects are installable at this point.
# Replaced by the real sources in the COPY below; pip has already resolved the
# dependency tree by then, which is the whole point of the split.
RUN mkdir -p packages/knowledge-schema/learnos_schema \
             services/sandbox/learnos_sandbox \
             apps/api/learnos_api \
 && touch packages/knowledge-schema/learnos_schema/__init__.py \
          services/sandbox/learnos_sandbox/__init__.py \
          apps/api/learnos_api/__init__.py \
 && pip install ./packages/knowledge-schema ./services/sandbox \
 && pip install ./apps/api

COPY packages/knowledge-schema/ packages/knowledge-schema/
COPY services/sandbox/ services/sandbox/
COPY apps/api/ apps/api/

# --no-deps: the dependency tree is already installed and resolved above; this
# pass only replaces the three local distributions with their real contents.
RUN pip install --no-deps --force-reinstall \
      ./packages/knowledge-schema ./services/sandbox ./apps/api

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is here for the healthcheck below and nothing else. No compiler, no git.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Non-root. The Docker socket is group-mounted in development, which is what
# lets an unprivileged user still launch sandbox containers; if the group id on
# the host socket differs, `make up` prints the sandbox as unavailable in
# /readyz rather than failing silently.
RUN useradd --create-home --uid 10001 learnos \
 && mkdir -p /app/var/objects /app/subjects \
 && chown -R learnos:learnos /app

WORKDIR /app
COPY --chown=learnos:learnos apps/api/alembic.ini ./alembic.ini
COPY --chown=learnos:learnos apps/api/migrations ./migrations

USER learnos

EXPOSE 8000

# Hits /healthz, not /readyz. Liveness must not depend on Postgres: a database
# restart would otherwise make compose kill and recreate a perfectly healthy API
# container, turning a ten-second blip into a restart loop.
HEALTHCHECK --interval=10s --timeout=3s --start-period=25s --retries=6 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "learnos_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
