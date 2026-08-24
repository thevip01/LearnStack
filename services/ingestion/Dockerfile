# LearnOS ingestion image.
#
# The only container in this system with outbound network access. Everything about
# the layout below follows from that.
#
# Build context is the repo root: this service depends on two local path packages,
# and one of them is the API. See storage/repository.py for why the SQLAlchemy
# models are shared rather than duplicated.
#
# `learnos-api` is installed with --no-deps and that is load-bearing, not an
# optimisation. It contributes twelve table declarations that import nothing but
# SQLAlchemy; installing it normally would drag FastAPI, uvicorn and the Docker SDK
# into the one container that can reach the internet. A crawler has no business
# holding a Docker client.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# lxml has manylinux wheels, but libxml2 headers are here so a platform without
# them still builds rather than failing three minutes into an image build.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc libxml2-dev libxslt1-dev \
 && rm -rf /var/lib/apt/lists/*

ENV VENV=/opt/venv
RUN python -m venv $VENV
ENV PATH="$VENV/bin:$PATH"

WORKDIR /src

# Dependency metadata first, sources second, so editing an adapter does not
# invalidate the layer that installed lxml.
COPY packages/knowledge-schema/pyproject.toml packages/knowledge-schema/
COPY apps/api/pyproject.toml apps/api/
COPY services/ingestion/pyproject.toml services/ingestion/

RUN mkdir -p packages/knowledge-schema/learnos_schema \
             apps/api/learnos_api \
             services/ingestion/learnos_ingestion \
 && touch packages/knowledge-schema/learnos_schema/__init__.py \
          apps/api/learnos_api/__init__.py \
          services/ingestion/learnos_ingestion/__init__.py \
 && pip install ./packages/knowledge-schema \
 && pip install --no-deps ./apps/api \
 && pip install ./services/ingestion

# Ordering above is the whole trick. learnos-api goes in first with --no-deps, so by
# the time pip resolves learnos-ingestion's `learnos-api>=0.1` the requirement is
# already satisfied by an installed distribution and pip neither hits an index nor
# pulls FastAPI. Reversing these two lines silently installs the entire web stack.

COPY packages/knowledge-schema/ packages/knowledge-schema/
COPY apps/api/learnos_api/ apps/api/learnos_api/
COPY services/ingestion/ services/ingestion/

RUN pip install --no-deps --force-reinstall \
      ./packages/knowledge-schema ./apps/api ./services/ingestion

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# No curl, no git, no compiler. This container makes outbound requests; it should
# not also contain convenient tools for making them by hand.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Non-root, and no Docker socket. Unlike the API image, this container never
# launches a sandbox. /app/subjects is mounted read-write by compose because the
# build stage writes into a package; /app/var/ingestion holds fetched bodies.
RUN useradd --create-home --uid 10002 ingest \
 && mkdir -p /app/var/ingestion /app/subjects \
 && chown -R ingest:ingest /app

WORKDIR /app
USER ingest

# No HEALTHCHECK: this is a CLI, not a server. A container that has finished its
# crawl and exited 0 is healthy, and compose would report it unhealthy forever.

ENTRYPOINT ["learnos-ingest"]
CMD ["--help"]
