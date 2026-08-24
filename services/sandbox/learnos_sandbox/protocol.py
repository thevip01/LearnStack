"""The sandbox contract: what a runner is, and how a workspace reaches one.

This module is deliberately tiny and dependency-light. It exists so that the API
never talks to Docker directly and never builds a tar by hand:

* ``Runner`` is the only interface the execution service programs against, which
  is what makes the Docker runner and the development subprocess runner
  interchangeable.
* ``pack_workspace`` is the single place a learner-controlled path is turned into
  an archive member. Every runner copies files *into* the sandbox with this
  archive rather than bind-mounting a host directory, because a bind mount is a
  writable hole in the host filesystem and a tar is not.
* ``unpack_result`` is the parser for the one line of structured output the
  in-container harness is allowed to print. Framing it with an unambiguous
  sentinel means learner code printing JSON cannot forge a test report.

The harness source is shipped as a *file in the workspace* rather than baked
into the runner image. That keeps the image generic (one Python image for every
subject) and means a harness bug is fixed by redeploying the API rather than by
rebuilding and redistributing images.
"""

from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from learnos_schema import ExecutionRequest, ExecutionResult, SourceFile

__all__ = [
    "HARNESS_FILENAME",
    "MANIFEST_FILENAME",
    "MAX_WORKSPACE_BYTES",
    "RESULT_SENTINEL",
    "RunOutcome",
    "Runner",
    "TestSpec",
    "WorkspaceError",
    "build_manifest",
    "harness_command",
    "harness_source",
    "normalise_path",
    "pack_workspace",
    "unpack_result",
]

#: Prefix on the harness's single line of structured output. Long and unlikely
#: on purpose: the parser takes the *last* line carrying it, so a learner who
#: prints the sentinel can add noise but cannot displace the real report, which
#: the harness writes after everything else has finished.
RESULT_SENTINEL = "__LEARNOS_RESULT_V1__"

HARNESS_FILENAME = "_learnos_harness.py"
MANIFEST_FILENAME = "_learnos_tests.json"

#: Total uncompressed size of a packed workspace. A submission is source code;
#: anything approaching this is either a mistake or an attempt to fill the
#: container's tmpfs before the memory limit can bite.
MAX_WORKSPACE_BYTES = 4 * 1024 * 1024

#: Fixed timestamp on every archive member. Reproducible archives make an
#: identical submission produce an identical tar, which is what allows the
#: execution layer to be cached or replayed later without surprises.
_FIXED_MTIME = 0


class WorkspaceError(ValueError):
    """A workspace could not be packed. Always a rejected input, never a bug."""


def normalise_path(path: str) -> str:
    """Validate and normalise one workspace-relative path.

    This is a security control and the last one before a string becomes an
    archive member name. Absolute paths, ``..`` traversal, drive letters,
    backslashes and NUL bytes are all rejected rather than sanitised, because a
    silently rewritten path is a submission that ran something other than what
    the learner wrote.
    """
    if not isinstance(path, str) or not path.strip():
        raise WorkspaceError("workspace file path must be a non-empty string")
    cleaned = path.strip().replace("\\", "/")
    if cleaned.startswith("/") or cleaned.startswith("~"):
        raise WorkspaceError(f"workspace file path must be relative: {path!r}")
    if ":" in cleaned:
        raise WorkspaceError(f"workspace file path may not contain a colon: {path!r}")
    if any(ch in cleaned for ch in ("\x00", "\n", "\r")):
        raise WorkspaceError(f"workspace file path contains control characters: {path!r}")
    parts = [part for part in cleaned.split("/") if part != "."]
    if not parts:
        raise WorkspaceError(f"workspace file path resolves to nothing: {path!r}")
    if any(part in ("", "..") for part in parts):
        raise WorkspaceError(f"workspace file path may not contain '..' or empty segments: {path!r}")
    if len(parts) > 12:
        raise WorkspaceError(f"workspace file path is nested too deeply: {path!r}")
    return "/".join(parts)


def _iter_pairs(files: Iterable[Any] | Mapping[str, str]) -> Iterable[tuple[str, str]]:
    if isinstance(files, Mapping):
        return list(files.items())
    pairs: list[tuple[str, str]] = []
    for entry in files:
        if isinstance(entry, SourceFile):
            pairs.append((entry.path, entry.content))
        elif isinstance(entry, tuple) and len(entry) == 2:
            pairs.append((str(entry[0]), str(entry[1])))
        elif hasattr(entry, "path") and hasattr(entry, "content"):
            pairs.append((str(entry.path), str(entry.content)))
        elif isinstance(entry, dict) and "path" in entry:
            pairs.append((str(entry["path"]), str(entry.get("content", ""))))
        else:
            raise WorkspaceError(f"cannot pack workspace entry of type {type(entry).__name__}")
    return pairs


def pack_workspace(
    files: Iterable[Any] | Mapping[str, str],
    *,
    extra: Mapping[str, str] | None = None,
    max_bytes: int = MAX_WORKSPACE_BYTES,
) -> bytes:
    """Build an uncompressed tar of a workspace, ready for ``put_archive``.

    Later entries win, so a caller can layer starter files, the learner's
    submission and the hidden test bodies in that order and get the expected
    result without having to de-duplicate first.

    Every member is written as a regular file owned by uid/gid 0 with mode 0644.
    No symlinks, no devices, no directories with odd modes: the archive is data,
    and a runner that extracts it as root inside a read-only container must not
    be able to be talked into creating anything else.
    """
    merged: dict[str, str] = {}
    for path, content in _iter_pairs(files):
        merged[normalise_path(path)] = content
    for path, content in (extra or {}).items():
        merged[normalise_path(path)] = content

    total = sum(len(content.encode("utf-8")) for content in merged.values())
    if total > max_bytes:
        raise WorkspaceError(f"workspace is {total} bytes, over the {max_bytes} byte limit")

    buffer = io.BytesIO()
    # No compression: the payload crosses a unix socket to a local daemon, and
    # gzip would cost CPU on the API process to save nothing measurable.
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in sorted(merged):
            payload = merged[path].encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(payload)
            info.mode = 0o644
            info.mtime = _FIXED_MTIME
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.type = tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


@dataclass
class TestSpec:
    """One authored test, as the harness needs to see it.

    ``functions`` is how a ``TestCase`` id is reconnected to a pytest node id
    without the harness having to guess. It is derived from the test body by the
    caller, which is the only party that has the body.
    """

    id: str
    name: str
    weight: float = 1.0
    file: str | None = None
    functions: list[str] = field(default_factory=list)
    node_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "weight": float(self.weight),
            "file": self.file,
            "functions": list(self.functions),
            "node_id": self.node_id,
        }


def build_manifest(tests: Sequence[TestSpec], *, targets: Sequence[str] | None = None) -> str:
    """Serialise the test manifest the harness reads out of the workspace.

    Note what is *not* in it: no test bodies and no expected values. The bodies
    are already on disk where pytest will find them; duplicating them into a
    manifest would put answer material in a second place that has to be
    remembered when redaction is audited.
    """
    payload = {
        "schema": 1,
        "tests": [spec.as_dict() for spec in tests],
        "targets": list(targets or []),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def harness_source() -> str:
    """Read the in-container harness so it can be injected into a workspace."""
    path = Path(__file__).with_name("harness") / "pytest_harness.py"
    return path.read_text(encoding="utf-8")


def harness_command() -> list[str]:
    """The command a runner executes to drive the harness.

    ``-I`` is isolated mode: no ``PYTHONPATH``, no user site-packages, and the
    script directory is *not* prepended blindly from the environment. It keeps a
    submitted ``sitecustomize.py`` or a stray env var from changing how the
    harness itself starts up.
    """
    return ["python", "-I", HARNESS_FILENAME]


def unpack_result(stdout: str) -> tuple[dict[str, Any] | None, str]:
    """Split a harness report out of captured stdout.

    Returns ``(payload, remaining_stdout)``. The payload is the last
    well-formed sentinel line; every sentinel line is stripped from the returned
    stdout so a learner cannot see a half-parsed report, and so that forged
    sentinel lines never reach the client either.
    """
    payload: dict[str, Any] | None = None
    kept: list[str] = []
    for line in stdout.splitlines():
        if line.startswith(RESULT_SENTINEL):
            raw = line[len(RESULT_SENTINEL) :].strip()
            try:
                candidate = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
            continue
        kept.append(line)
    remaining = "\n".join(kept)
    if stdout.endswith("\n") and remaining:
        remaining += "\n"
    return payload, remaining


@dataclass
class RunOutcome:
    """Everything one execution produced.

    The harness's structured report is kept *beside* the ``ExecutionResult``
    rather than on it, for two reasons that reinforce each other:

    * ``ExecutionResult`` is a ``SchemaModel`` with ``extra="forbid"``, so there
      is no field for the report to occupy, and that is the point. The result is
      the object serialised straight to the client; if the report were a field on
      it, keeping hidden test failure text out of HTTP responses would depend on
      somebody remembering to strip it.
    * The report contains assertion text for *every* test, visible or not.
      Forcing the caller to ask for it separately means the redaction step in the
      grader is impossible to skip by accident.
    """

    result: ExecutionResult
    report: dict[str, Any] | None = None


@runtime_checkable
class Runner(Protocol):
    """A thing that can execute an ``ExecutionRequest`` and report what happened.

    Implementations must never raise for a learner-caused failure. Failing
    tests, a syntax error, an infinite loop and a memory blow-up are all
    *successful executions* that return a result with the appropriate status; an
    exception out of ``run`` means the platform broke, and the API turns that
    into ``sandbox_unavailable``.
    """

    #: ``"docker"`` or ``"subprocess"``. Surfaced by ``/readyz``.
    name: str

    async def available(self) -> bool:
        """Cheap liveness probe, called at startup and by ``/readyz``."""
        ...

    async def run(
        self,
        request: ExecutionRequest,
        *,
        execution_id: str,
        image: str | None = None,
        output_limit_bytes: int = 64_000,
        workspace_extra: Mapping[str, str] | None = None,
    ) -> RunOutcome:
        """Execute and return a terminal result plus any harness report."""
        ...

    async def close(self) -> None:
        """Release any client held open. Idempotent."""
        ...
