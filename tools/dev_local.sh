#!/usr/bin/env bash
#
# Run the whole of LearnOS on a laptop with no infrastructure at all.
#
# `make up` is the honest way to run this project: Postgres, Redis, the API, the
# web app and a sandbox runner image, wired the way production is wired. This
# script exists for the other case, which is far more common in practice: someone
# has just cloned the repo, does not have Docker running, and wants to see the
# thing work before deciding whether to care about it.
#
# What it gives up, and why that is safe here:
#
#   Postgres  -> SQLite via aiosqlite. Every query in the API goes through
#                SQLAlchemy Core with no Postgres-only constructs on the learner
#                paths, so the app is genuinely exercised. What you lose is the
#                pgvector hybrid search: `search_index_built hybrid=False` in the
#                log means the lexical index is live and the vector half is not.
#   Redis     -> nothing. The cache layer already degrades to a no-op and logs
#                `cache_set_failed`. Correctness does not depend on it, only
#                latency, and at one-user scale that is unmeasurable.
#   Docker    -> SANDBOX_MODE=subprocess. This is the one real compromise, and
#                it is why this script refuses to run with ENV=production below.
#                Learner code runs as your user with your filesystem and your
#                network. Fine for the demo content, which you wrote. Not fine
#                for anything you did not.
#
# Everything else is the real application: real auth, real mastery scoring, real
# grading, real curriculum sequencing, the real Next.js front end.
#
# Usage:
#   tools/dev_local.sh              # API on 8000, web on 3000
#   tools/dev_local.sh --api-only   # skip the web app
#   API_PORT=8100 WEB_PORT=3100 tools/dev_local.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
API_ONLY=0
[[ "${1:-}" == "--api-only" ]] && API_ONLY=1

VENV="$ROOT/.venv"
STATE="$ROOT/var/local"
mkdir -p "$STATE"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Refuse to be used as a deployment
# ---------------------------------------------------------------------------
# The subprocess sandbox is a remote code execution primitive by design. The
# config module already refuses to boot with it in production, but failing here
# is better than failing after the ports are bound and something is talking to
# it.
case "${ENV:-development}" in
  development|dev|local|test) ;;
  *) die "ENV=$ENV. This script runs an unsandboxed interpreter and must never serve real users. Use 'make up'." ;;
esac

# ---------------------------------------------------------------------------
# Python side
# ---------------------------------------------------------------------------
# Three of the four packages declare `requires-python = ">=3.12"` and the runner
# image is python:3.12, so 3.12 is the floor rather than a preference. pip
# enforces it during the install and reports "Package 'learnos-schema' requires a
# different Python", which is a confusing thing to hit several minutes in.
#
# Preferring an explicit python3.12 over plain `python3` matters most on macOS,
# where `python3` is often the Command Line Tools build (3.9) even when a newer
# Homebrew or pyenv interpreter is installed and on PATH under its versioned name.
PYBIN=""
for candidate in "${PYTHON:-}" python3.14 python3.13 python3.12 python3; do
  [[ -n "$candidate" ]] || continue
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYBIN="$(command -v "$candidate")"
    break
  fi
done
if [[ -z "$PYBIN" ]]; then
  found="$(python3 -V 2>&1 || echo none)"
  die "need Python 3.12 or newer, found $found.
    macOS:  brew install python@3.12
    then:   PYTHON=python3.12 tools/dev_local.sh"
fi
PYV="$("$PYBIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# An existing venv built by an interpreter that is now too old would fail the same
# way, and "delete .venv" is not obvious. Say so and rebuild.
if [[ -x "$VENV/bin/python" ]] && \
   ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
  bold "$VENV was built with $("$VENV/bin/python" -V 2>&1), which is too old. Rebuilding it."
  rm -rf "$VENV"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  bold "creating $VENV (python $PYV)"
  "$PYBIN" -m venv "$VENV"
fi

# Reinstall only when something is actually missing. A dependency check is
# cheap; a four-package editable install on every boot is thirty seconds that
# makes people stop using the script.
if ! "$VENV/bin/python" -c "import learnos_api, learnos_schema, learnos_sandbox, learnos_ingestion" 2>/dev/null; then
  bold "installing python packages (first run only)"
  # setuptools as well as pip, and not as a reflex. Every pyproject here declares
  # `requires = ["setuptools>=68"]` and installs editable, which needs PEP 660's
  # `build_editable` hook, added in setuptools 64. Distros still ship 59 (Ubuntu
  # 22.04 does), and when build isolation cannot reach PyPI to honour the
  # requirement, pip falls back to the ambient version and fails with "build
  # backend is missing the 'build_editable' hook", which reads like a bug in this
  # repo rather than a stale toolchain.
  "$VENV/bin/pip" install --quiet --upgrade pip setuptools wheel
  "$VENV/bin/pip" install --quiet \
    -e "packages/knowledge-schema[dev]" \
    -e "services/sandbox[dev]" \
    -e "apps/api[dev]" \
    -e "services/ingestion[dev]"
fi
# aiosqlite is not a dependency of the API: Postgres is, and adding a second
# driver to pyproject would imply SQLite is a supported backend. It is not. It
# is a convenience for this script, so this script is what installs it.
"$VENV/bin/python" -c "import aiosqlite" 2>/dev/null || \
  "$VENV/bin/pip" install --quiet aiosqlite

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
export ENV=development
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export API_PORT
export DATABASE_URL="sqlite+aiosqlite:///$STATE/api.db"
# Loopback rather than the compose hostname `redis`, so the failure is an
# instant connection refused instead of a DNS lookup on every cache call.
export REDIS_URL="redis://127.0.0.1:6379/0"
export SUBJECTS_DIR="$ROOT/subjects"
export OBJECT_STORAGE_DIR="$STATE/objects"
export SANDBOX_MODE=subprocess
export AUTO_CREATE_SCHEMA=true
export SEED_DEMO_USER=true
export JWT_SECRET="${JWT_SECRET:-dev-only-secret-not-for-anything-real}"
export CORS_ORIGINS="http://localhost:$WEB_PORT"

PIDS=()
SERVICE_PIDS=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  printf '\nstopped.\n'
}
trap cleanup INT TERM EXIT

# `/dev/tcp` rather than lsof or nc, neither of which is guaranteed to be present.
# The fd is closed explicitly because a successful connect leaves it open, and a
# dangling descriptor on the port we are about to bind is a confusing thing to
# debug later.
port_free() {
  if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then
    exec 3>&- 2>/dev/null || true
    return 1
  fi
  return 0
}
port_free "$API_PORT" || die "port $API_PORT is already in use (another API? 'lsof -ti:$API_PORT' to find it)"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
bold "starting the API on http://127.0.0.1:$API_PORT"
( cd "$ROOT/apps/api" && exec "$VENV/bin/python" -m uvicorn learnos_api.main:app \
    --host 127.0.0.1 --port "$API_PORT" ) >"$STATE/api.log" 2>&1 &
API_PID=$!
PIDS+=("$API_PID")
SERVICE_PIDS+=("$API_PID")

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$API_PORT/readyz" >/dev/null 2>&1; then break; fi
  kill -0 "$API_PID" 2>/dev/null || { tail -30 "$STATE/api.log"; die "the API exited during startup"; }
  sleep 1
done
curl -fsS "http://127.0.0.1:$API_PORT/readyz" >/dev/null 2>&1 || {
  tail -30 "$STATE/api.log"; die "the API did not become ready within 60s"
}
dim "  $(curl -fsS "http://127.0.0.1:$API_PORT/readyz")"

# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------
if [[ "$API_ONLY" == "0" ]]; then
  command -v node >/dev/null || die "node not found. Install Node 20+ or run with --api-only."
  NODEV="$(node -p 'process.versions.node.split(".")[0]')"
  (( NODEV >= 20 )) || die "node $NODEV found; Next 15 needs 20 or newer."

  [[ -d "$ROOT/apps/web/node_modules/next" ]] || {
    bold "installing web dependencies (first run only)"
    ( cd "$ROOT/apps/web" && npm install )
  }

  port_free "$WEB_PORT" || die "port $WEB_PORT is already in use"

  # Both variables, deliberately. `apps/web/src/lib/api.ts` picks a different
  # base depending on whether the call is running in the browser or in the Next
  # server, and the server-side default is the compose hostname `http://api:8000`
  # which does not exist outside Docker. Set only the public one and every page
  # renders server-side against a host that is not there, which shows up as an
  # empty dashboard rather than as an error.
  export NEXT_PUBLIC_API_URL="http://127.0.0.1:$API_PORT"
  export API_INTERNAL_URL="http://127.0.0.1:$API_PORT"

  bold "starting the web app on http://localhost:$WEB_PORT"
  ( cd "$ROOT/apps/web" && exec ./node_modules/.bin/next dev --port "$WEB_PORT" ) \
    >"$STATE/web.log" 2>&1 &
  WEB_PID=$!
  PIDS+=("$WEB_PID")
  SERVICE_PIDS+=("$WEB_PID")

  # next dev compiles the first route on demand, so the first response can take
  # a while on a cold .next directory. Failing fast here would be wrong.
  for _ in $(seq 1 150); do
    if curl -fsS --max-time 40 -o /dev/null "http://127.0.0.1:$WEB_PORT/"; then break; fi
    kill -0 "$WEB_PID" 2>/dev/null || {
      tail -40 "$STATE/web.log"
      die "the web app exited during startup. If this says 'Failed to load SWC binary', your node_modules were installed on a different OS or CPU: delete apps/web/node_modules and run 'npm install' again."
    }
    sleep 2
  done
fi

# ---------------------------------------------------------------------------
# Where to go
# ---------------------------------------------------------------------------
DEMO_EMAIL="${DEMO_USER_EMAIL:-demo@learnos.dev}"
DEMO_PASS="${DEMO_USER_PASSWORD:-learnos-demo-2026}"

echo
bold "LearnOS is up"
if [[ "$API_ONLY" == "0" ]]; then
  echo "  app          http://localhost:$WEB_PORT"
  echo "  sign in      $DEMO_EMAIL / $DEMO_PASS"
  echo "  start here   http://localhost:$WEB_PORT/subjects/programming.python"
  echo "               http://localhost:$WEB_PORT/progress/programming.python"
fi
echo "  api docs     http://localhost:$API_PORT/docs"
echo "  readiness    http://localhost:$API_PORT/readyz"
echo
dim "  sqlite   $STATE/api.db     (delete it to reset all progress)"
if [[ "$API_ONLY" == "0" ]]; then
  dim "  logs     $STATE/api.log  $STATE/web.log"
else
  dim "  logs     $STATE/api.log"
fi
dim "  sandbox  subprocess mode: learner code runs as $(whoami) with no isolation"
echo
dim "Ctrl-C to stop both."

# Surface the logs so the terminal is useful rather than silent.
#
# `tail -f` runs in the background on purpose. As the script's last foreground
# command it would block bash from running the EXIT trap until it returned, so
# Ctrl-C left the API and the web server alive: a real terminal sends SIGINT to
# the whole foreground process group and papers over it, but anything that signals
# this script by pid does not, and neither does `kill`.
#
# The wait is a poll rather than `wait -n` because macOS still ships bash 3.2,
# where `wait -n` does not exist. Sleeping in one second slices also means a trap
# fires within a second instead of whenever a long command happens to finish.
if [[ "$API_ONLY" == "0" ]]; then
  tail -n 0 -f "$STATE/api.log" "$STATE/web.log" &
else
  tail -n 0 -f "$STATE/api.log" &
fi
PIDS+=("$!")

while :; do
  for pid in "${SERVICE_PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '\na service exited on its own. Check the logs above.\n'
      break 2
    fi
  done
  sleep 1
done
