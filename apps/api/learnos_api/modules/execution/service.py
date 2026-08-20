"""The execution service: one queue, one runner, one place that persists a run.

Responsibilities, in the order they matter:

1. **Decide which runner is live** and report it honestly. ``SANDBOX_MODE=docker``
   means "refuse rather than silently downgrade"; ``auto`` prefers Docker and
   falls back; ``subprocess`` is an explicit development choice. The answer
   appears in ``/readyz`` so the web app can warn.
2. **Bound concurrency.** A semaphore sized by ``EXECUTION_MAX_CONCURRENCY`` is
   what keeps total sandbox memory predictable when thirty learners submit at
   once. Without it, container memory limits are per-container and the host has
   no limit at all.
3. **Keep learner code out of the API process.** Nothing here imports, ``exec``s
   or ``eval``s a submission. It packs files and hands them to a runner.
4. **Persist a run** as an ``executions`` row with output in object storage, so a
   202 response has something to poll.

The service never grades. Turning an ``ExecutionResult`` into a score is the
practice module's job, because that is where the visibility rules for hidden
tests live.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Mapping

from learnos_schema import ExecutionRequest, ExecutionResult, ExecutionStatus, ResourceUsage, TestResult
from learnos_sandbox import (
    HARNESS_FILENAME,
    MANIFEST_FILENAME,
    RunOutcome,
    TestSpec,
    build_manifest,
    harness_source,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings
from ...db import session_scope
from ...errors import SandboxUnavailable
from ...logging import get_logger
from ...models import Execution
from ...schemas.health import SandboxState
from ..subjects.registry import SubjectRegistry
from .docker_runner import DockerRunner
from .storage import ObjectStore
from .subprocess_runner import SubprocessRunner

logger = get_logger(__name__)

#: The contract: a run whose declared timeout is under this is answered inline
#: with 200; anything longer gets a 202 and is polled. Five seconds is the point
#: at which a browser request stops feeling like a request.
INLINE_TIMEOUT_LIMIT_S = 5


def status_value(result: ExecutionResult) -> str:
    """The status as a plain string.

    ``SchemaModel`` sets ``use_enum_values=True``, so ``result.status`` is already
    a ``str`` after validation even though the annotation says ``ExecutionStatus``.
    Comparing it with ``is`` against an enum member silently returns False, which
    is a trap worth one helper.
    """
    value = result.status
    return value.value if isinstance(value, ExecutionStatus) else str(value)


def succeeded(result: ExecutionResult) -> bool:
    return status_value(result) == ExecutionStatus.SUCCEEDED.value


class ExecutionService:
    """Owns the runner, the semaphore and the execution records."""

    def __init__(
        self,
        settings: Settings,
        *,
        registry: SubjectRegistry | None = None,
        store: ObjectStore | None = None,
        runner: object | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._store = store or ObjectStore(settings.object_storage_path)
        self._semaphore = asyncio.Semaphore(settings.EXECUTION_MAX_CONCURRENCY)
        self._runner = runner
        self._state: SandboxState = "unavailable"
        self._background: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Startup / probing
    # ------------------------------------------------------------------

    @property
    def sandbox_state(self) -> SandboxState:
        return self._state

    @property
    def store(self) -> ObjectStore:
        return self._store

    async def probe(self) -> SandboxState:
        """Pick a runner and remember which one. Safe to call repeatedly.

        Called at startup and again from ``/readyz``, so a Docker daemon that dies
        and comes back is noticed without a restart.
        """
        if self._runner is not None and self._state != "unavailable":
            # An injected runner (tests) or an already-chosen one: re-probe only.
            if await self._runner.available():  # type: ignore[attr-defined]
                return self._state
            self._state = "unavailable"

        mode = self._settings.SANDBOX_MODE
        if self._runner is not None and self._state == "unavailable":
            available = await self._runner.available()  # type: ignore[attr-defined]
            self._state = getattr(self._runner, "name", "unavailable") if available else "unavailable"
            return self._state

        if mode in ("auto", "docker"):
            docker_runner = DockerRunner(
                base_url=self._settings.DOCKER_HOST or None,
                network=self._settings.SANDBOX_NETWORK if self._settings.sandbox_network_enabled else None,
            )
            if await docker_runner.available():
                self._runner = docker_runner
                self._state = "docker"
                logger.info("sandbox.mode", mode="docker")
                return self._state
            await docker_runner.close()
            if mode == "docker":
                # Explicitly requested Docker and it is not there. Refusing is the
                # only honest answer: falling back would run learner code with far
                # weaker isolation than the operator asked for.
                self._runner = None
                self._state = "unavailable"
                logger.error("sandbox.docker_required_but_missing")
                return self._state

        self._runner = SubprocessRunner()
        await self._runner.available()
        self._state = "subprocess"
        logger.warning("sandbox.mode", mode="subprocess", isolation="weak")
        return self._state

    async def close(self) -> None:
        for task in list(self._background):
            task.cancel()
        self._background.clear()
        runner = self._runner
        if runner is not None and hasattr(runner, "close"):
            await runner.close()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Image selection
    # ------------------------------------------------------------------

    def image_for(self, request: ExecutionRequest) -> str | None:
        """Resolve the pinned image for the requested runtime.

        A subject package cannot name an arbitrary image: the runtime kind is
        looked up in the registry's pinned table, so "run this in
        ``attacker/evil:latest``" is not expressible.
        """
        if self._registry is None:
            return None
        limits = request.limits
        spec = self._registry.resolve_runtime(str(limits.runtime), limits.runtime_version)
        return spec.image if spec else None

    def default_command_for(self, request: ExecutionRequest) -> str | None:
        if self._registry is None:
            return None
        limits = request.limits
        spec = self._registry.resolve_runtime(str(limits.runtime), limits.runtime_version)
        return spec.default_command if spec else None

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    def should_run_inline(self, request: ExecutionRequest) -> bool:
        return int(request.limits.timeout_s) <= INLINE_TIMEOUT_LIMIT_S

    async def execute(
        self,
        request: ExecutionRequest,
        *,
        execution_id: str | None = None,
        image: str | None = None,
        workspace_extra: Mapping[str, str] | None = None,
    ) -> RunOutcome:
        """Run one request. Raises only when the *platform* cannot run it."""
        if self._runner is None or self._state == "unavailable":
            # Try once more: the daemon may have come back since startup.
            await self.probe()
        if self._runner is None or self._state == "unavailable":
            raise SandboxUnavailable("code execution is unavailable right now")

        run_id = execution_id or str(uuid.uuid4())
        chosen_image = image or self.image_for(request)
        async with self._semaphore:
            try:
                outcome = await self._runner.run(  # type: ignore[attr-defined]
                    request,
                    execution_id=run_id,
                    image=chosen_image,
                    output_limit_bytes=self._settings.EXECUTION_OUTPUT_LIMIT_BYTES,
                    workspace_extra=workspace_extra,
                )
            except Exception as exc:  # noqa: BLE001
                # A runner raising means the platform broke, not the submission.
                logger.exception("execution.runner_crashed", execution_id=run_id, error=str(exc))
                raise SandboxUnavailable("code execution failed unexpectedly") from exc
        logger.info(
            "execution.finished",
            execution_id=run_id,
            status=status_value(outcome.result),
            runner=outcome.result.runner,
            duration_ms=outcome.result.usage.duration_ms,
        )
        return outcome

    async def run_tests(
        self,
        request: ExecutionRequest,
        *,
        specs: list[TestSpec],
        execution_id: str | None = None,
        image: str | None = None,
    ) -> RunOutcome:
        """Run a request under the pytest harness.

        The harness and its manifest are injected as workspace files rather than
        being part of the request, so they can never be overwritten by a learner's
        submitted files: ``pack_workspace`` applies ``extra`` last.
        """
        extra = {
            HARNESS_FILENAME: harness_source(),
            MANIFEST_FILENAME: build_manifest(specs),
        }
        patched = request.model_copy(update={"command": request.command or "python -I " + HARNESS_FILENAME})
        return await self.execute(patched, execution_id=execution_id, image=image, workspace_extra=extra)

    # ------------------------------------------------------------------
    # Queued (202) runs
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        request: ExecutionRequest,
        *,
        user_id: uuid.UUID | None,
        task_id: str | None = None,
    ) -> str:
        """Insert a queued row, start the run in the background, return its id.

        The row is written before this returns so that the ``execution_id`` handed
        back in the 202 is immediately pollable — a client that polls faster than
        we insert would otherwise get a 404 for a run that exists.
        """
        execution_id = str(uuid.uuid4())
        image = self.image_for(request)
        async with session_scope() as session:
            session.add(
                Execution(
                    id=uuid.UUID(execution_id),
                    user_id=user_id,
                    status=ExecutionStatus.QUEUED.value,
                    runtime=str(request.limits.runtime),
                    image=image,
                    runner=self._state if self._state != "unavailable" else "docker",
                    task_id=task_id,
                    started_at=_utcnow(),
                )
            )

        task = asyncio.create_task(self._run_background(request, execution_id, user_id, task_id, image))
        # Hold a reference: a bare create_task can be garbage collected mid-flight.
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return execution_id

    async def _run_background(
        self,
        request: ExecutionRequest,
        execution_id: str,
        user_id: uuid.UUID | None,
        task_id: str | None,
        image: str | None,
    ) -> None:
        try:
            outcome = await self.execute(request, execution_id=execution_id, image=image)
            result = outcome.result
        except SandboxUnavailable as exc:
            result = ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.INTERNAL_ERROR,
                runner="docker",
                error=str(exc.message),
                usage=ResourceUsage(),
                started_at=_utcnow(),
                finished_at=_utcnow(),
            )
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("execution.background_failed", execution_id=execution_id, error=str(exc))
            result = ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.INTERNAL_ERROR,
                runner="docker",
                error="the run failed unexpectedly",
                started_at=_utcnow(),
                finished_at=_utcnow(),
            )
        async with session_scope() as session:
            await self.record(session, result, user_id=user_id, task_id=task_id, image=image, runtime=str(request.limits.runtime))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def record(
        self,
        session: AsyncSession,
        result: ExecutionResult,
        *,
        user_id: uuid.UUID | None,
        runtime: str,
        image: str | None = None,
        task_id: str | None = None,
    ) -> Execution:
        """Insert or update the ``executions`` row for a finished run.

        Output goes to object storage first: if that fails the row still lands with
        null refs, which is a run you can see but whose logs are gone — strictly
        better than losing the record of the run.
        """
        stdout_ref = None
        stderr_ref = None
        if result.stdout:
            stdout_ref = await self._store.put_text(self._store.key_for(result.execution_id, "stdout.txt"), result.stdout)
        if result.stderr:
            stderr_ref = await self._store.put_text(self._store.key_for(result.execution_id, "stderr.txt"), result.stderr)

        row = await session.get(Execution, uuid.UUID(result.execution_id))
        if row is None:
            row = Execution(id=uuid.UUID(result.execution_id), started_at=result.started_at)
            session.add(row)
        row.user_id = user_id
        row.status = status_value(result)
        row.runtime = runtime
        row.image = image
        row.runner = result.runner
        row.task_id = task_id
        row.usage = result.usage.model_dump(mode="json")
        row.tests = [test.model_dump(mode="json") for test in result.tests]
        row.artifacts = dict(result.artifacts)
        row.stdout_ref = stdout_ref
        row.stderr_ref = stderr_ref
        row.truncated = bool(result.truncated)
        row.error = result.error
        row.finished_at = result.finished_at
        row.duration_ms = int(result.usage.duration_ms or 0)
        return row

    async def load(
        self,
        session: AsyncSession,
        execution_id: str,
        *,
        user_id: uuid.UUID | None,
    ) -> ExecutionResult | None:
        """Rehydrate a stored run for ``GET /execution/runs/{id}``.

        Ownership is enforced here rather than in the route: an execution holds a
        learner's code and output, and "anyone with the uuid can read it" is not a
        boundary.
        """
        try:
            key = uuid.UUID(execution_id)
        except (ValueError, AttributeError):
            return None
        row = await session.get(Execution, key)
        if row is None:
            return None
        if row.user_id is not None and row.user_id != user_id:
            return None
        stdout = await self._store.get_text(row.stdout_ref)
        stderr = await self._store.get_text(row.stderr_ref)
        return ExecutionResult(
            execution_id=str(row.id),
            status=row.status,
            stdout=stdout,
            stderr=stderr,
            truncated=row.truncated,
            usage=ResourceUsage.model_validate(row.usage or {}),
            tests=[TestResult.model_validate(test) for test in (row.tests or [])],
            artifacts=dict(row.artifacts or {}),
            runner=row.runner,
            error=row.error,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    async def recent_for_user(self, session: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> list[Execution]:
        stmt = select(Execution).where(Execution.user_id == user_id).order_by(Execution.created_at.desc()).limit(limit)
        return list((await session.execute(stmt)).scalars().all())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
