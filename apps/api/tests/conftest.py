"""Fixtures for the API suite.

Four deliberate choices, because each one is the kind of thing a later reader
would otherwise "simplify" back into a slow or flaky suite.

**The real app, through ASGI, with the real lifespan.** Every test here drives
``create_app`` over ``httpx.ASGITransport`` and enters ``app.router.lifespan_context``
by hand, because ``ASGITransport`` does not run startup events. That costs a second
per test and buys the only thing worth buying: the wiring. Table creation, subject
loading, the search index install, the execution probe and the demo seed all run,
so a route that works in isolation but is mounted at the wrong prefix, or a
dependency that was never populated on ``app.state``, fails here rather than in
front of the user.

**A fresh SQLite database per test.** ``tmp_path`` is function scoped, so every test
gets an empty database and can assert on exact numbers. Mastery is a weighted mean
over evidence rows, which means a shared database turns "debugging evidence is worth
0.70" into "somewhere near 0.70, depending on what ran first". Sharing the database
would also make the suite order dependent, which is the failure mode that gets a
suite disabled instead of fixed. The API's models are SQLite safe on purpose, see
``models/base.py``.

**No Postgres, no Redis, no Docker.** ``REDIS_URL`` points at a closed port so the
cache helpers take their documented degraded path (they return ``None`` or ``0``
rather than raising), which also means the rate limiters fail open and cannot make
the suite flaky by counting requests across tests. Sandbox-backed grading is not
tested here at all: it needs a real runner, and it is covered end to end by
``tools/verify_loop.sh``. What is left, quiz grading and the whole mastery path, is
pure Python and runs anywhere.

**bcrypt is turned down to its cheapest setting.** Production uses 12 rounds, about
a quarter second per hash, and the demo seed plus a handful of register and login
tests would spend most of the suite's runtime inside a KDF proving nothing. The cost
factor is a property of the deployment, not of the code under test, and it is
asserted where it belongs in ``test_auth.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncIterator

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SUBJECTS_DIR = REPO_ROOT / "subjects"

# Importable without an editable install, for the same reason the schema suite does
# this: a locked down image or an offline sandbox can still run the tests. The insert
# is a no-op when `pip install -e` has already happened.
for _path in (
    API_ROOT,
    REPO_ROOT / "packages" / "knowledge-schema",
    REPO_ROOT / "services" / "sandbox",
    REPO_ROOT / "services" / "ingestion",
):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# Set before `learnos_api` is imported. `main.py` builds a module level `app` at
# import time, which calls the `lru_cache`d `get_settings()`, so without this the
# cache would be primed with the production defaults (a Postgres URL and the
# container's /app/subjects) from the first import onward. Each test still gets its
# own explicit Settings; this only stops the ambient ones from being wrong.
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SUBJECTS_DIR", str(SUBJECTS_DIR))
os.environ.setdefault("SEED_DEMO_USER", "false")

import httpx  # noqa: E402  (after the path inserts, on purpose)
from passlib.context import CryptContext  # noqa: E402

from learnos_api.config import Settings, get_settings  # noqa: E402
from learnos_api.main import create_app  # noqa: E402
from learnos_api.modules.auth import passwords  # noqa: E402

# The one production constant this suite deliberately overrides. See the module
# docstring; `test_auth.py::test_password_hashing_uses_a_real_cost_factor` pins the
# real value so this shortcut cannot quietly become the deployed one.
passwords._context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)

DEMO_EMAIL = "demo@learnos.dev"
DEMO_PASSWORD = "learnos-demo-2026"

SUBJECT = "programming.python"
QUIZ = "python.practice.closures.check.late-binding"
CODE = "python.practice.closures.code.counter-factory"
DEBUG = "python.practice.closures.debug.late-binding-loop"
SKILL = "python.skill.reason-about-closures"

#: Every question in the quiz, so a submission can be a clean 5/5.
ALL_CORRECT = {
    "closures.the-classic-loop": "a",
    "closures.default-arg-capture": "a",
    "closures.nonlocal-required": "a",
    "closures.what-is-captured": ["a", "b"],
    "closures.shared-cell": "a",
}
#: Two of the five, which scores 0.4 and misses the task's 0.8 threshold.
TWO_CORRECT = {
    "closures.the-classic-loop": "a",
    "closures.default-arg-capture": "a",
}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "subjects: needs the real subject packages on disk")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: everything on disk points into ``tmp_path``, nothing at a service.

    ``ENV="test"`` matters twice. It puts ``is_development`` on, so the lifespan does
    not refuse to boot over ``insecure_defaults()``, and it turns off ``cookie_secure``
    so the session cookie survives a plain http test transport.
    """
    if not (SUBJECTS_DIR / "programming" / "python" / "manifest.json").is_file():
        pytest.skip("no subject packages on disk")
    return Settings(
        ENV="test",
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        # A port nothing listens on, so `ping_redis` fails fast and locally instead
        # of waiting on a DNS lookup for a container that is not there.
        REDIS_URL="redis://127.0.0.1:1/0",
        SUBJECTS_DIR=str(SUBJECTS_DIR),
        OBJECT_STORAGE_DIR=str(tmp_path / "objects"),
        SANDBOX_MODE="subprocess",
        SEED_DEMO_USER=True,
        AUTO_CREATE_SCHEMA=True,
        # 32+ bytes, because PyJWT warns below that for HS256 and a suite that
        # prints warnings is a suite whose warnings stop being read.
        JWT_SECRET="test-only-secret-long-enough-for-hs256",
    )


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """The whole app, booted, behind an httpx client that keeps cookies."""
    app = create_app(settings)
    # `Depends(get_settings)` would otherwise hand routes the cached ambient
    # settings rather than this test's.
    app.dependency_overrides[get_settings] = lambda: settings
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.app = app  # type: ignore[attr-defined]  # a couple of tests reach for app.state
            yield client


@pytest.fixture
async def learner(api: httpx.AsyncClient) -> httpx.AsyncClient:
    """``api``, signed in as the seeded demo account.

    Login rather than a forged token or a `current_user` override, so the cookie
    path that the browser actually uses is the one under test.
    """
    response = await api.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return api


async def start_attempt(api: httpx.AsyncClient, task_id: str) -> str:
    response = await api.post(f"/api/v1/practice/{task_id}/attempts")
    assert response.status_code == 201, response.text
    return response.json()["attempt_id"]


async def submit_quiz(
    api: httpx.AsyncClient, attempt_id: str, answers: dict, *, task_id: str = QUIZ
) -> dict:
    response = await api.post(
        f"/api/v1/practice/{task_id}/attempts/{attempt_id}/submit",
        json={"kind": "quiz", "answers": answers},
    )
    assert response.status_code == 200, response.text
    return response.json()


def dimension(progress: dict, dimension_name: str, skill_id: str = SKILL) -> dict:
    """One dimension of one skill out of a ``/progress/{subject}`` body."""
    skills = [s for s in progress["skills"] if s["skill_id"] == skill_id]
    assert skills, f"{skill_id} is missing from the progress response"
    return skills[0]["dimensions"][dimension_name]
