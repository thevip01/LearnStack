"""Docker-backed sandbox runner.

Read ``services/sandbox/README.md`` before changing anything in this file. Every
container flag below is a defence against a specific attack, and the reasons are
written down there rather than repeated at each keyword argument.

Two structural points that are easy to undo by accident:

* **The workspace is copied in with ``put_archive``. There are no bind mounts.**
  A bind mount is a writable hole in the host filesystem; a tar is data. If you
  find yourself adding ``volumes=`` here, you are removing the primary isolation
  guarantee to save a few milliseconds.
* **Every Docker SDK call is blocking**, so the whole run happens inside one
  ``asyncio.to_thread``. Calling ``container.wait()`` from a coroutine directly
  would stall the event loop for the duration of a learner's infinite loop, and
  one bad submission would look like an outage.
"""

from __future__ import annotations

import asyncio
import io
import shlex
import tarfile
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from learnos_schema import ExecutionRequest, ExecutionResult, ExecutionStatus, ResourceUsage
from learnos_sandbox import RunOutcome, pack_workspace, unpack_result

from ...logging import get_logger

try:  # pragma: no cover - import shape depends on the environment
    import docker
    from docker.errors import DockerException, ImageNotFound, NotFound
except Exception:  # noqa: BLE001 - the SDK is optional at import time
    docker = None  # type: ignore[assignment]

    class DockerException(Exception):  # type: ignore[no-redef]
        pass

    class ImageNotFound(DockerException):  # type: ignore[no-redef]
        pass

    class NotFound(DockerException):  # type: ignore[no-redef]
        pass


logger = get_logger(__name__)

WORKSPACE = "/workspace"
STDIN_FILE = "_learnos_stdin.txt"

#: Extra wall-clock allowance on top of the task's timeout before we stop waiting
#: and kill. Container start-up and image lookup are not the learner's time.
TIMEOUT_GRACE_S = 8

#: Size of the writable tmpfs. tmpfs is RAM, so this is part of the memory budget
#: and is deliberately much smaller than ``memory_mb``.
WORKSPACE_TMPFS_MB = 32
TMP_TMPFS_MB = 16

#: Cap on the artifact tar we are willing to pull back out of a container.
ARTIFACT_LIMIT_BYTES = 256 * 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DockerRunner:
    """Runs one ``ExecutionRequest`` in a locked-down throwaway container."""

    name = "docker"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        network: str | None = None,
        default_image: str = "learnos/runner-python:3.12",
    ) -> None:
        self._base_url = base_url
        # ``None`` means "no network at all". A name here is only ever used by a
        # task that explicitly declared it needs egress.
        self._network = network or None
        self._default_image = default_image
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    def _connect_sync(self) -> Any:
        if docker is None:  # pragma: no cover
            raise DockerException("the docker SDK is not installed")
        if self._base_url:
            return docker.DockerClient(base_url=self._base_url, timeout=30)
        return docker.from_env(timeout=30)

    async def _client_or_none(self) -> Any | None:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                self._client = await asyncio.to_thread(self._connect_sync)
            except Exception as exc:  # noqa: BLE001 - absence of Docker is normal
                logger.info("sandbox.docker_unavailable", error=str(exc))
                return None
        return self._client

    async def available(self) -> bool:
        client = await self._client_or_none()
        if client is None:
            return False
        try:
            return bool(await asyncio.to_thread(client.ping))
        except Exception as exc:  # noqa: BLE001
            logger.warning("sandbox.docker_ping_failed", error=str(exc))
            # Drop the client so the next probe reconnects rather than reusing a
            # socket to a daemon that has gone away.
            self._client = None
            return False

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.to_thread(client.close)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    async def run(
        self,
        request: ExecutionRequest,
        *,
        execution_id: str,
        image: str | None = None,
        output_limit_bytes: int = 64_000,
        workspace_extra: Mapping[str, str] | None = None,
    ) -> RunOutcome:
        client = await self._client_or_none()
        if client is None:
            return RunOutcome(self._platform_failure(execution_id, "the sandbox is not available"))
        return await asyncio.to_thread(
            self._run_sync,
            client,
            request,
            execution_id,
            image or self._default_image,
            output_limit_bytes,
            dict(workspace_extra or {}),
        )

    def _platform_failure(self, execution_id: str, message: str) -> ExecutionResult:
        now = _utcnow()
        return ExecutionResult(
            execution_id=execution_id,
            status=ExecutionStatus.INTERNAL_ERROR,
            runner=self.name,
            error=message,
            started_at=now,
            finished_at=now,
        )

    def _container_kwargs(self, request: ExecutionRequest, image: str, command: list[str]) -> dict[str, Any]:
        limits = request.limits
        wants_network = str(limits.network) != "none" and self._network is not None
        env = {
            # Unbuffered so output already flushed survives a kill; no bytecode
            # because the root filesystem is read-only.
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": WORKSPACE,
            "TMPDIR": "/tmp",
            "LEARNOS_SANDBOX": "1",
        }
        # Task-declared env last, but it can never grant capability — the
        # container has none to grant. Secrets are explicitly not passed here.
        env.update({str(k): str(v) for k, v in (request.env or {}).items()})

        memory = f"{int(limits.memory_mb)}m"
        kwargs: dict[str, Any] = {
            "image": image,
            "command": command,
            "working_dir": WORKSPACE,
            # uid 65534. Belt and braces with the image's own non-root USER.
            "user": "nobody",
            "detach": True,
            "stdin_open": False,
            "tty": False,
            # No writable root filesystem: nothing can be dropped in /usr/local/bin
            # and nothing persists.
            "read_only": True,
            "tmpfs": {
                WORKSPACE: f"rw,size={WORKSPACE_TMPFS_MB}m,mode=1777,nosuid,nodev,noexec",
                # pytest and tempfile need a writable /tmp; read_only takes it away.
                "/tmp": f"rw,size={TMP_TMPFS_MB}m,mode=1777,nosuid,nodev,noexec",
            },
            "mem_limit": memory,
            # Same as mem_limit: without this the container can swap its way past
            # the memory cap instead of being OOM-killed.
            "memswap_limit": memory,
            "nano_cpus": int(float(limits.cpu_limit) * 1_000_000_000),
            "pids_limit": int(limits.pids_limit),
            "cap_drop": ["ALL"],
            # Without this, a setuid binary in the image undoes cap_drop.
            "security_opt": ["no-new-privileges"],
            "environment": env,
            "labels": {"learnos.sandbox": "1"},
            # We remove the container ourselves in a finally block; auto_remove
            # races with reading logs and inspecting the exit state.
            "auto_remove": False,
            "network_disabled": not wants_network,
        }
        if wants_network:
            kwargs["network"] = self._network
            # Phase 2: egress_allowlist is enforced by attaching to a network
            # whose egress is filtered upstream. The API records the intent; the
            # filtering is a deployment concern, not a container flag.
        return kwargs

    def _command_for(self, request: ExecutionRequest, workspace_extra: Mapping[str, str]) -> list[str]:
        raw = (request.command or "").strip()
        if not raw:
            raw = "python -I _learnos_harness.py" if "_learnos_harness.py" in workspace_extra else "python main.py"
        if request.stdin is None:
            return shlex.split(raw)
        # Docker's create API has no "feed this string to stdin" option that does
        # not involve attaching a stream, so stdin arrives as a file and the
        # command is redirected from it. `exec` keeps the pid count at one, which
        # matters when pids_limit is small.
        return ["/bin/sh", "-c", f"exec {raw} < {shlex.quote(STDIN_FILE)}"]

    def _run_sync(
        self,
        client: Any,
        request: ExecutionRequest,
        execution_id: str,
        image: str,
        output_limit_bytes: int,
        workspace_extra: dict[str, str],
    ) -> RunOutcome:
        started = _utcnow()
        monotonic = time.monotonic()

        extra = dict(workspace_extra)
        if request.stdin is not None:
            extra[STDIN_FILE] = request.stdin
        try:
            archive = pack_workspace(request.files, extra=extra)
        except ValueError as exc:
            # A bad path is the caller's fault, not a platform failure, but there
            # is no learner-facing story for it either: reject loudly.
            return RunOutcome(self._platform_failure(execution_id, f"workspace rejected: {exc}"))

        command = self._command_for(request, extra)
        kwargs = self._container_kwargs(request, image, command)

        container = None
        timed_out = False
        exit_code: int | None = None
        oom = False
        state: dict[str, Any] = {}
        try:
            try:
                container = client.containers.create(**kwargs)
            except ImageNotFound:
                return RunOutcome(
                    self._platform_failure(
                        execution_id,
                        f"sandbox image {image!r} is missing; build it with 'make runner'",
                    )
                )
            container.put_archive(WORKSPACE, archive)
            container.start()

            timeout = int(request.limits.timeout_s) + TIMEOUT_GRACE_S
            try:
                status = container.wait(timeout=timeout)
                exit_code = int(status.get("StatusCode", -1))
            except Exception as wait_exc:  # noqa: BLE001 - requests timeouts vary
                # The SDK surfaces a wait timeout as a requests ConnectionError,
                # which is indistinguishable by type from a daemon that died. Ask
                # the daemon what actually happened instead of guessing.
                still_running = self._is_running(container)
                if still_running:
                    timed_out = True
                    self._kill(container)
                    exit_code = 137
                else:
                    logger.warning("sandbox.wait_failed", execution_id=execution_id, error=str(wait_exc))
                    exit_code = self._exit_code(container)

            state = self._state(container)
            oom = bool(state.get("OOMKilled"))
            if exit_code is None:
                exit_code = state.get("ExitCode")

            stdout, stdout_cut = self._read_logs(container, output_limit_bytes, stdout=True)
            stderr, stderr_cut = self._read_logs(container, output_limit_bytes, stdout=False)
            artifacts = self._collect_artifacts(container, request.collect_artifacts)
        except DockerException as exc:
            logger.warning("sandbox.docker_error", execution_id=execution_id, error=str(exc))
            return RunOutcome(self._platform_failure(execution_id, "the sandbox failed to run this submission"))
        finally:
            self._remove(container)

        report, stdout = unpack_result(stdout)
        duration_ms = int((time.monotonic() - monotonic) * 1000)

        # Order matters. A timeout that also happened to OOM is still a timeout
        # from the learner's point of view, and exit 137 on its own means only
        # "killed by SIGKILL", which is why OOMKilled is consulted rather than
        # inferred.
        if timed_out:
            status_value = ExecutionStatus.TIMEOUT
        elif oom:
            status_value = ExecutionStatus.OOM
        elif exit_code == 0:
            status_value = ExecutionStatus.SUCCEEDED
        else:
            status_value = ExecutionStatus.FAILED

        result = ExecutionResult(
            execution_id=execution_id,
            status=status_value,
            stdout=stdout,
            stderr=stderr,
            truncated=stdout_cut or stderr_cut,
            usage=ResourceUsage(
                duration_ms=duration_ms,
                exit_code=exit_code,
                # max_memory_mb is left unset rather than guessed: cgroup peak
                # usage is not reliably readable once the container is gone, and
                # a wrong number here would be shown to a learner as fact.
            ),
            artifacts=artifacts,
            runner=self.name,
            error=self._error_note(status_value),
            started_at=started,
            finished_at=_utcnow(),
        )
        return RunOutcome(result, report)

    @staticmethod
    def _error_note(status_value: ExecutionStatus) -> str | None:
        if status_value is ExecutionStatus.TIMEOUT:
            return "execution exceeded the time limit and was stopped"
        if status_value is ExecutionStatus.OOM:
            return "execution exceeded the memory limit and was stopped"
        return None

    # ------------------------------------------------------------------
    # Daemon interrogation, all failure-tolerant
    # ------------------------------------------------------------------

    @staticmethod
    def _state(container: Any) -> dict[str, Any]:
        try:
            container.reload()
            state = container.attrs.get("State") or {}
            return state if isinstance(state, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _is_running(self, container: Any) -> bool:
        return bool(self._state(container).get("Running"))

    def _exit_code(self, container: Any) -> int | None:
        code = self._state(container).get("ExitCode")
        return int(code) if isinstance(code, int) else None

    @staticmethod
    def _kill(container: Any) -> None:
        try:
            container.kill()
        except Exception:  # noqa: BLE001 - already dead is the happy path
            pass

    @staticmethod
    def _remove(container: Any) -> None:
        if container is None:
            return
        try:
            container.remove(force=True, v=True)
        except NotFound:
            pass
        except Exception as exc:  # noqa: BLE001
            # A leaked container is a leaked memory/cpu reservation, so this is
            # worth a warning even though there is nothing to do about it here.
            logger.warning("sandbox.container_leak", error=str(exc))

    @staticmethod
    def _read_logs(container: Any, limit: int, *, stdout: bool) -> tuple[str, bool]:
        """Stream logs, stopping at ``limit`` bytes.

        Streaming rather than one ``logs()`` call is the difference between an
        infinite print loop costing us ``limit`` bytes and it costing us however
        much the daemon buffered.
        """
        chunks: list[bytes] = []
        total = 0
        truncated = False
        try:
            stream = container.logs(stdout=stdout, stderr=not stdout, stream=True, follow=False)
        except Exception:  # noqa: BLE001
            return "", False
        try:
            for chunk in stream:
                if not chunk:
                    continue
                remaining = limit - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total = limit
                    truncated = True
                    break
                chunks.append(chunk)
                total += len(chunk)
        except Exception:  # noqa: BLE001 - a broken stream is not fatal
            pass
        finally:
            closer = getattr(stream, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if truncated:
            text += "\n... [output truncated]"
        return text, truncated

    @staticmethod
    def _collect_artifacts(container: Any, patterns: list[str]) -> dict[str, str]:
        """Best-effort retrieval of declared artifact files.

        Only used by project-style tasks that ask for a report. It is best-effort
        because ``/workspace`` is a tmpfs and may already be gone by the time the
        container has exited; a missing artifact must never fail a submission.
        """
        if not patterns:
            return {}
        import fnmatch

        collected: dict[str, str] = {}
        try:
            stream, _stat = container.get_archive(WORKSPACE, encode_stream=False)
            buffer = io.BytesIO()
            size = 0
            for chunk in stream:
                size += len(chunk)
                if size > ARTIFACT_LIMIT_BYTES:
                    return {}
                buffer.write(chunk)
            buffer.seek(0)
            with tarfile.open(fileobj=buffer, mode="r") as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    relative = member.name.split("workspace/", 1)[-1]
                    if not any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
                        continue
                    handle = archive.extractfile(member)
                    if handle is None:
                        continue
                    collected[relative] = handle.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.info("sandbox.artifacts_unavailable", error=str(exc))
            return {}
        return collected
