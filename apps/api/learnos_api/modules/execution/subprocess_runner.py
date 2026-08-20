"""Development-only fallback runner.

**This is not a security boundary.** It runs learner code as the API's own user,
on the API's own filesystem, with the API's own network access. It exists so that
``make dev-api`` works on a laptop without Docker, and it says so loudly at
startup and in ``/readyz`` (``"sandbox": "subprocess"``), because a silent
downgrade from container isolation to "same uid, different directory" is exactly
the kind of thing that ships to production by accident.

What it *does* do, all via ``resource.setrlimit`` in the child before ``exec``:

* caps CPU seconds, so an infinite loop dies even if the async timeout is missed
* caps address space, which turns runaway allocation into ``MemoryError``
* caps file size, so nothing can fill the disk
* caps process count, which is the answer to a fork bomb
* disables core dumps

And outside the child: a fresh temporary directory per run, a minimal
environment, its own process group so the whole tree can be killed, and the same
output cap as the Docker runner.

What it cannot do: stop the code reading your ``~/.ssh``, connecting to your
database, or deleting your files. Use Docker.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from learnos_schema import ExecutionRequest, ExecutionResult, ExecutionStatus, ResourceUsage
from learnos_sandbox import RunOutcome, normalise_path, unpack_result

from ...logging import get_logger

try:  # pragma: no cover - POSIX only; Windows has no rlimits
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

logger = get_logger(__name__)

STDIN_FILE = "_learnos_stdin.txt"

#: The CPython interpreter itself needs headroom before it can even import
#: pytest. Applying a 64 MB address-space limit would kill startup and look like
#: the learner's fault, so the floor is well above any task's declared limit.
MIN_ADDRESS_SPACE_MB = 512

MAX_FILE_SIZE_BYTES = 8 * 1024 * 1024
READ_CHUNK = 8192


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SubprocessRunner:
    """Runs a request in a child process with rlimits and a temp workspace."""

    name = "subprocess"

    def __init__(self, *, python_executable: str | None = None, warn: bool = True) -> None:
        self._python = python_executable or sys.executable or "python3"
        if warn:
            logger.warning(
                "sandbox.subprocess_mode",
                message=(
                    "Sandbox is running in subprocess mode. Learner code executes as this "
                    "process's user with full filesystem and network access. Development only."
                ),
            )

    async def available(self) -> bool:
        # Nothing to probe: if the interpreter is running, a child can be forked.
        # rlimits are the only optional part, and their absence is reported so the
        # weaker mode is still visible rather than assumed.
        if resource is None:  # pragma: no cover
            logger.warning("sandbox.no_rlimits", platform=sys.platform)
        return True

    async def close(self) -> None:
        return None

    # ------------------------------------------------------------------

    def _limits_preexec(self, request: ExecutionRequest) -> Any:
        """Build the ``preexec_fn`` that clamps the child before ``exec``.

        ``preexec_fn`` runs after ``fork`` and before ``exec`` in the child. It is
        documented as unsafe in threaded programs because it runs arbitrary Python
        between the two; the calls here are limited to ``setrlimit``, which is
        async-signal-safe, and this is the only mechanism the standard library
        offers for per-child rlimits.
        """
        if resource is None:  # pragma: no cover
            return None

        cpu_seconds = max(1, int(request.limits.timeout_s))
        address_space = max(int(request.limits.memory_mb), MIN_ADDRESS_SPACE_MB) * 1024 * 1024
        pids = max(8, int(request.limits.pids_limit))

        def _apply() -> None:  # pragma: no cover - runs in the forked child
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
            resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_BYTES))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (pids, pids))
            except (ValueError, OSError):
                # RLIMIT_NPROC is per-uid, not per-process, so on some systems
                # setting it below the current usage fails. Losing the fork-bomb
                # cap is survivable in a mode that is already not a boundary.
                pass

        return _apply

    @staticmethod
    def _write_workspace(root: Path, request: ExecutionRequest, extra: Mapping[str, str]) -> None:
        payload: dict[str, str] = {}
        for source in request.files:
            payload[normalise_path(source.path)] = source.content
        for path, content in extra.items():
            payload[normalise_path(path)] = content
        if request.stdin is not None:
            payload[STDIN_FILE] = request.stdin
        for relative, content in payload.items():
            target = root / relative
            resolved = target.resolve()
            # normalise_path already rejected traversal; this asserts the outcome
            # rather than trusting it, because the cost is one syscall.
            if root.resolve() not in resolved.parents:
                raise ValueError(f"refusing to write outside the workspace: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _argv(self, request: ExecutionRequest, extra: Mapping[str, str]) -> list[str]:
        raw = (request.command or "").strip()
        if not raw:
            raw = "python -I _learnos_harness.py" if "_learnos_harness.py" in extra else "python main.py"
        argv = shlex.split(raw)
        if argv and argv[0] in ("python", "python3"):
            # Use the interpreter the API is running under. "python" may not
            # exist on PATH, and if it does it is probably not the same one.
            argv[0] = self._python
        return argv

    async def run(
        self,
        request: ExecutionRequest,
        *,
        execution_id: str,
        image: str | None = None,
        output_limit_bytes: int = 64_000,
        workspace_extra: Mapping[str, str] | None = None,
    ) -> RunOutcome:
        # ``image`` is meaningless here; accepted so the two runners are
        # substitutable behind the Runner protocol.
        del image
        started = _utcnow()
        monotonic = time.monotonic()
        extra = dict(workspace_extra or {})

        workspace = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="learnos-run-"))
        try:
            try:
                await asyncio.to_thread(self._write_workspace, workspace, request, extra)
            except ValueError as exc:
                return RunOutcome(self._failure(execution_id, started, f"workspace rejected: {exc}"))

            argv = self._argv(request, extra)
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(workspace),
                "TMPDIR": str(workspace),
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "LEARNOS_SANDBOX": "1",
                "LC_ALL": "C.UTF-8",
            }
            env.update({str(k): str(v) for k, v in (request.env or {}).items()})

            stdin_target = None
            if request.stdin is not None:
                stdin_target = await asyncio.to_thread(open, workspace / STDIN_FILE, "rb")

            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=str(workspace),
                    env=env,
                    stdin=stdin_target or asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    # Its own session, so a kill reaches every grandchild rather
                    # than orphaning a busy loop.
                    start_new_session=True,
                    preexec_fn=self._limits_preexec(request),
                )
            except FileNotFoundError:
                return RunOutcome(self._failure(execution_id, started, f"command not found: {argv[0]!r}"))
            except OSError as exc:
                return RunOutcome(self._failure(execution_id, started, f"could not start the process: {exc}"))
            finally:
                if stdin_target is not None:
                    stdin_target.close()

            out_task = asyncio.create_task(_read_capped(process.stdout, output_limit_bytes))
            err_task = asyncio.create_task(_read_capped(process.stderr, output_limit_bytes))

            timed_out = False
            try:
                exit_code = await asyncio.wait_for(process.wait(), timeout=int(request.limits.timeout_s) + 2)
            except asyncio.TimeoutError:
                timed_out = True
                _kill_group(process)
                exit_code = -9
                # Reap so no zombie is left behind, but do not wait forever for a
                # process that is ignoring SIGKILL (it cannot, but be defensive).
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:  # pragma: no cover
                    pass

            stdout_bytes, stdout_cut = await _settle(out_task)
            stderr_bytes, stderr_cut = await _settle(err_task)
        finally:
            await asyncio.to_thread(shutil.rmtree, workspace, True)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if stdout_cut:
            stdout += "\n... [output truncated]"
        if stderr_cut:
            stderr += "\n... [output truncated]"
        report, stdout = unpack_result(stdout)

        if timed_out:
            status = ExecutionStatus.TIMEOUT
        elif "MemoryError" in stderr or exit_code == -int(signal.SIGKILL):
            # RLIMIT_AS surfaces as MemoryError inside Python; a bare SIGKILL with
            # no timeout is almost always the kernel or the rlimit reacting to
            # memory. Reporting "out of memory" is more useful than "killed".
            status = ExecutionStatus.OOM
        elif exit_code == 0:
            status = ExecutionStatus.SUCCEEDED
        else:
            status = ExecutionStatus.FAILED

        result = ExecutionResult(
            execution_id=execution_id,
            status=status,
            stdout=stdout,
            stderr=stderr,
            truncated=stdout_cut or stderr_cut,
            usage=ResourceUsage(
                duration_ms=int((time.monotonic() - monotonic) * 1000),
                exit_code=exit_code,
            ),
            runner=self.name,
            error=_error_note(status),
            started_at=started,
            finished_at=_utcnow(),
        )
        return RunOutcome(result, report)

    def _failure(self, execution_id: str, started: datetime, message: str) -> ExecutionResult:
        return ExecutionResult(
            execution_id=execution_id,
            status=ExecutionStatus.INTERNAL_ERROR,
            runner=self.name,
            error=message,
            started_at=started,
            finished_at=_utcnow(),
        )


def _error_note(status: ExecutionStatus) -> str | None:
    if status is ExecutionStatus.TIMEOUT:
        return "execution exceeded the time limit and was stopped"
    if status is ExecutionStatus.OOM:
        return "execution exceeded the memory limit and was stopped"
    return None


async def _read_capped(stream: Any, limit: int) -> tuple[bytes, bool]:
    """Read up to ``limit`` bytes, then keep draining and discarding.

    Draining matters: if we stopped reading, the child would block on a full pipe
    and a program that printed a lot but would otherwise finish correctly would be
    reported as a timeout.
    """
    if stream is None:  # pragma: no cover
        return b"", False
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while True:
        chunk = await stream.read(READ_CHUNK)
        if not chunk:
            break
        if total >= limit:
            truncated = True
            continue
        room = limit - total
        if len(chunk) > room:
            chunks.append(chunk[:room])
            total = limit
            truncated = True
            continue
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), truncated


async def _settle(task: "asyncio.Task[tuple[bytes, bool]]") -> tuple[bytes, bool]:
    try:
        return await asyncio.wait_for(task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        task.cancel()
        return b"", True


def _kill_group(process: Any) -> None:
    """SIGKILL the whole process group; fall back to the single process."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except ProcessLookupError:  # pragma: no cover
            pass
