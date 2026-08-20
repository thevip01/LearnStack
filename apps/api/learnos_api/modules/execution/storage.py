"""Object storage for execution output.

Learner output is unbounded in practice, so ``executions.stdout_ref`` holds a key
into this store rather than the text itself (see ``models/execution.py``). The
implementation is the local filesystem because that is what a laptop and a single
container both have; the interface is narrow enough that swapping in S3 is a new
class and no caller changes.

Keys are generated here and never accepted from a client. ``_resolve`` still
re-checks that the resulting path is inside the root, because "this key is
internal" is the kind of statement that stops being true two refactors later.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from ...logging import get_logger

logger = get_logger(__name__)

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,250}$")


class ObjectStore:
    """A tiny content store keyed by opaque strings."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def key_for(self, execution_id: str, name: str) -> str:
        return f"executions/{execution_id}/{name}"

    def _resolve(self, key: str) -> Path:
        if not _SAFE_KEY.match(key) or ".." in key.split("/"):
            raise ValueError(f"unsafe object key {key!r}")
        path = (self._root / key).resolve()
        root = self._root.resolve()
        if root != path and root not in path.parents:
            raise ValueError(f"object key escapes the storage root: {key!r}")
        return path

    def _put_sync(self, key: str, text: str) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return key

    def _get_sync(self, key: str) -> str | None:
        try:
            path = self._resolve(key)
        except ValueError:
            logger.warning("object_store.bad_key", key=key)
            return None
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    async def put_text(self, key: str, text: str) -> str:
        """Write text, returning the key. Blocking IO is pushed off the loop."""
        return await asyncio.to_thread(self._put_sync, key, text)

    async def get_text(self, key: str | None) -> str:
        """Read text back, or ``""`` when the key is missing.

        A missing object is not an error: output is expendable, and an execution
        record whose logs have been pruned should still be readable.
        """
        if not key:
            return ""
        value = await asyncio.to_thread(self._get_sync, key)
        return value or ""

    async def ensure_root(self) -> bool:
        """Create the root directory. Returns False if the volume is unusable."""

        def _mk() -> bool:
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                probe = self._root / ".writable"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return True
            except OSError as exc:
                logger.warning("object_store.unwritable", path=str(self._root), error=str(exc))
                return False

        return await asyncio.to_thread(_mk)
