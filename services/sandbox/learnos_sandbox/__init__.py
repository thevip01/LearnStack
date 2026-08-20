"""LearnOS sandbox contracts and the in-container test harness.

The API depends on this package for two things and nothing else: the ``Runner``
protocol it programs against, and the helpers that turn a set of files into an
archive plus the harness that reads the results back out. Keeping them here
rather than inside ``apps/api`` means a second consumer (a remote sandbox host,
a CLI that reproduces a submission locally) can speak the same protocol without
importing the web application.
"""

from .protocol import (
    HARNESS_FILENAME,
    MANIFEST_FILENAME,
    MAX_WORKSPACE_BYTES,
    RESULT_SENTINEL,
    Runner,
    RunOutcome,
    TestSpec,
    WorkspaceError,
    build_manifest,
    harness_command,
    harness_source,
    normalise_path,
    pack_workspace,
    unpack_result,
)

__version__ = "0.1.0"

__all__ = [
    "HARNESS_FILENAME",
    "MANIFEST_FILENAME",
    "MAX_WORKSPACE_BYTES",
    "RESULT_SENTINEL",
    "RunOutcome",
    "Runner",
    "TestSpec",
    "WorkspaceError",
    "__version__",
    "build_manifest",
    "harness_command",
    "harness_source",
    "normalise_path",
    "pack_workspace",
    "unpack_result",
]
