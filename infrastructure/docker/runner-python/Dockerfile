# LearnOS Python sandbox runner.
#
# This image is the execution environment for learner-submitted Python. It is
# built locally (`make runner`, or `docker compose --profile images build`) and
# never pulled from a registry, because a sandbox image is the last place you
# want an unreviewed layer.
#
# Design rules, all of which have a security or determinism reason:
#
#   * Pinned base digest-free tag `python:3.12-slim` matching the runtime version
#     declared by subject packages. See README.md for why versions are pinned.
#   * pytest and pytest-json-report only. No requests, no numpy, no compiler
#     toolchain. Every package present is a capability handed to a hostile
#     process, and a package that can open a socket is a bypass of the network
#     restriction the moment someone enables egress for one task.
#   * A non-root `runner` user, and a `/workspace` it owns. The execution service
#     *also* forces `user=nobody` at run time; both exist so the image is safe
#     even if a future caller forgets the flag.
#   * No ENTRYPOINT that assumes a shape. The execution service passes the
#     command, because the command comes from the task definition.
FROM python:3.12-slim

# Pinned exactly: this is the code that decides whether a submission passed, so
# an unattended minor bump changing report shape would silently break grading.
# pytest-json-report is what the in-container harness prefers; the harness has an
# inline fallback so the image still works if this ever has to be dropped.
RUN pip install --no-cache-dir \
      "pytest==8.3.2" \
      "pytest-json-report==1.5.0" \
 && find /usr/local -name '__pycache__' -type d -prune -exec rm -rf {} + \
 && rm -rf /root/.cache

# uid/gid are fixed so that a workspace archive extracted as root is readable by
# the unprivileged user the container actually runs as.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin runner \
 && mkdir -p /workspace \
 && chown runner:runner /workspace \
 && chmod 0777 /workspace

# Unbuffered so that output from a process about to be killed on timeout has
# already been flushed; no .pyc writes because the root filesystem is read-only
# at run time and a failed write is a confusing traceback.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/workspace

WORKDIR /workspace
USER runner

# Sanity check only. The real command always comes from the execution service.
CMD ["python", "-c", "import pytest, sys; print('learnos runner-python', sys.version.split()[0], 'pytest', pytest.__version__)"]
