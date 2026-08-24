"""The two probes an orchestrator actually reads.

The rule under test is the one written down in ``api/health.py``: Postgres is the
only hard dependency, so it is the only thing that may turn ``/readyz`` into a 503.
This used to fail on any degraded dependency, which made ``make up`` time out on a
machine with no runner image even though the app was serving every request
correctly. A readiness probe that fails while the service works is worse than no
probe, because it teaches everyone to ignore it.
"""

from __future__ import annotations

import httpx
import pytest

from learnos_api.api import health


async def test_healthz_is_a_liveness_probe_and_never_depends_on_anything(api: httpx.AsyncClient):
    response = await api.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readyz_stays_200_while_only_optional_dependencies_are_degraded(
    api: httpx.AsyncClient,
):
    response = await api.get("/readyz")
    body = response.json()

    assert response.status_code == 200, body
    # Redis is not running in this suite and the sandbox is the development
    # fallback, so this is the degraded-but-serving case, reported honestly.
    assert body["postgres"] is True
    assert body["redis"] is False
    assert body["status"] == "degraded"


async def test_readyz_reports_which_sandbox_is_in_use_rather_than_just_a_boolean(
    api: httpx.AsyncClient,
):
    # A silent downgrade from container isolation to "same uid, different directory"
    # is exactly the thing that reaches production by accident, so the mode is on
    # the wire, not only in a log line.
    assert (await api.get("/readyz")).json()["sandbox"] in {"docker", "subprocess", "unavailable"}


async def test_readyz_turns_503_when_the_database_is_gone(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def no_database() -> bool:
        return False

    monkeypatch.setattr(health, "ping_database", no_database)

    response = await api.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


async def test_every_response_carries_a_request_id_and_the_version(api: httpx.AsyncClient):
    response = await api.get("/healthz")
    assert response.headers.get("x-request-id")
    assert response.headers.get("x-learnos-version")
