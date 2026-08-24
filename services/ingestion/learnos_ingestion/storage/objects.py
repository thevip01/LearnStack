"""Raw fetched bytes on disk, addressed by content hash.

Content-addressed rather than keyed by document id, which gives deduplication for
free: a docs site that serves the same boilerplate page under six URLs stores it
once. It also makes the store immutable (a hash never points at different bytes),
so a stale read is impossible and there is nothing to invalidate.

Sharded two levels deep by the first four hex characters. One flat directory with
200,000 entries makes ``ls`` unusable and, on some filesystems, lookups linear.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class RawStore:
    """Write-once storage for fetched bodies."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, content_hash: str) -> Path:
        if len(content_hash) < 4:
            raise ValueError(f"content hash {content_hash!r} is too short to shard")
        return self.root / content_hash[:2] / content_hash[2:4] / content_hash

    def exists(self, content_hash: str) -> bool:
        return self.path_for(content_hash).is_file()

    def put(self, content_hash: str, body: bytes) -> str:
        """Store ``body`` and return its storage key.

        A hash that already exists is not rewritten. That is not merely an
        optimisation: rewriting would open a window where a reader sees a
        half-written file, and since the content cannot have changed there is
        nothing to gain by taking that risk.

        The write is atomic (temp file then ``replace``), so a crash mid-crawl
        leaves either the whole body or nothing, never a truncated document that
        would hash differently on the next run and look like a content change.
        """
        target = self.path_for(content_hash)
        if target.is_file():
            return self.key_for(content_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".part")
        temp.write_bytes(body)
        temp.replace(target)
        return self.key_for(content_hash)

    def get(self, content_hash: str) -> bytes | None:
        target = self.path_for(content_hash)
        if not target.is_file():
            return None
        return target.read_bytes()

    def key_for(self, content_hash: str) -> str:
        """The value stored in ``RawDocument.raw_ref``.

        A relative logical key, not an absolute path: the API container and the
        ingestion container mount this volume at different points, and an absolute
        path in a database column would be wrong in one of them.
        """
        return f"raw/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}"

    def stats(self) -> dict[str, int]:
        count = 0
        total = 0
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if path.is_file() and path.suffix != ".part":
                    count += 1
                    total += path.stat().st_size
        return {"objects": count, "bytes": total}

    def prune(self, keep: set[str]) -> int:
        """Delete bodies whose hash is not in ``keep``.

        Only safe to call with the full set of live hashes across *every* source,
        which is why the pipeline never calls it and the CLI exposes it as an
        explicit ``gc`` command. A prune computed from one source's documents would
        delete the shared boilerplate page every other source also points at.
        """
        removed = 0
        if not self.root.is_dir():
            return 0
        for path in list(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix == ".part" or path.name not in keep:
                path.unlink(missing_ok=True)
                removed += 1
        for directory in sorted((p for p in self.root.rglob("*") if p.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def nuke(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
