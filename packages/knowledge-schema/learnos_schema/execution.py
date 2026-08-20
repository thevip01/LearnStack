"""Execution contract.

The same request/result pair covers running a snippet from a lesson, submitting a
code task, and executing a project milestone. The execution service knows nothing
about learning; it takes files and limits and returns what happened.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field

from .common import Id, SchemaModel, utcnow
from .practice import SandboxLimits, SourceFile


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    OOM = "oom"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"

    @property
    def is_terminal(self) -> bool:
        return self is not ExecutionStatus.QUEUED and self is not ExecutionStatus.RUNNING


class ExecutionRequest(SchemaModel):
    files: list[SourceFile] = Field(min_length=1)
    limits: SandboxLimits = Field(default_factory=SandboxLimits)
    command: str | None = Field(default=None, description="Defaults to the runner image entrypoint for the runtime.")
    stdin: str | None = None
    env: dict[str, str] = Field(default_factory=dict, description="Never used for secrets. Sandbox env is not private.")
    collect_artifacts: list[str] = Field(
        default_factory=list, description="Glob patterns of files to return, e.g. reports or trained model metrics."
    )


class TestResult(SchemaModel):
    test_id: Id
    name: str
    passed: bool
    weight: float = 1.0
    duration_ms: int | None = None
    message: str | None = Field(default=None, description="Assertion output. Redacted for hidden tests.")
    traceback: str | None = None


class ResourceUsage(SchemaModel):
    duration_ms: int = 0
    max_memory_mb: float | None = None
    cpu_ms: int | None = None
    exit_code: int | None = None


class ExecutionResult(SchemaModel):
    execution_id: str
    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    truncated: bool = Field(default=False, description="Output exceeded the capture cap and was cut.")
    usage: ResourceUsage = Field(default_factory=ResourceUsage)
    tests: list[TestResult] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    runner: Literal["docker", "subprocess"] = "docker"
    error: str | None = Field(default=None, description="Platform-level failure, distinct from learner code failing.")
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None

    @property
    def weighted_score(self) -> float:
        if not self.tests:
            return 1.0 if self.status is ExecutionStatus.SUCCEEDED else 0.0
        total = sum(t.weight for t in self.tests)
        if total == 0:
            return 0.0
        return sum(t.weight for t in self.tests if t.passed) / total
