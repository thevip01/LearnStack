"""Health and execution envelopes."""

from __future__ import annotations

from typing import Literal

from .common import ApiModel

SandboxState = Literal["docker", "subprocess", "unavailable"]


class HealthOut(ApiModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadyOut(ApiModel):
    status: Literal["ready", "degraded"]
    postgres: bool
    redis: bool
    #: The web app shows a banner when this is not ``docker``, because subprocess
    #: mode is a development fallback with materially weaker isolation.
    sandbox: SandboxState


class ExecutionQueuedOut(ApiModel):
    """202 response for a run too long to hold a request open for."""

    execution_id: str
