"""The raw object store.

Small surface, and every method exists to make one guarantee: a hash never points at
different bytes. That immutability is what lets the pipeline re-read a body it fetched
in an earlier run and trust that the chunk ids derived from it still describe it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from learnos_ingestion.hashing import content_hash
from learnos_ingestion.storage.objects import RawStore


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")


class TestPathFor:
    def test_shards_two_levels_deep(self, store: RawStore) -> None:
        """One flat directory with 200,000 entries makes ``ls`` unusable and, on some
        filesystems, makes lookups linear."""
        digest = "abcdef1234567890"
        assert store.path_for(digest) == store.root / "ab" / "cd" / digest

    def test_refuses_a_hash_too_short_to_shard(self, store: RawStore) -> None:
        """Silently falling back to an unsharded path would put a file where no reader
        looks for it, which reads as data loss rather than as a bug."""
        with pytest.raises(ValueError, match="too short"):
            store.path_for("ab")

    def test_the_logical_key_is_relative(self, store: RawStore) -> None:
        """``raw_ref`` goes in a database column read by two containers that mount this
        volume at different points. An absolute path would be wrong in one of them."""
        digest = "abcdef1234567890"
        key = store.key_for(digest)
        assert not key.startswith("/")
        assert key == f"raw/ab/cd/{digest}"
        assert str(store.root) not in key


class TestPut:
    def test_round_trips(self, store: RawStore) -> None:
        body = b"<html>docs</html>"
        digest = content_hash(body)
        store.put(digest, body)
        assert store.get(digest) == body
        assert store.exists(digest)

    def test_leaves_no_partial_file_behind(self, store: RawStore) -> None:
        """The write is temp-then-replace. A ``.part`` surviving a successful put would
        be counted by ``stats`` and deleted by ``prune``, both of which lie about what
        the store holds."""
        digest = content_hash(b"body")
        store.put(digest, b"body")
        assert not list(store.root.rglob("*.part"))

    def test_an_existing_hash_is_not_rewritten(self, store: RawStore) -> None:
        """Not merely an optimisation.

        Rewriting opens a window where a reader sees a half-written file, and since the
        content cannot have changed there is nothing to gain by taking that risk. The
        second put here would be a no-op even if the bytes disagreed — which they
        cannot, because the key is the hash of the bytes.
        """
        digest = content_hash(b"original")
        store.put(digest, b"original")
        mtime = store.path_for(digest).stat().st_mtime_ns
        store.put(digest, b"original")
        assert store.path_for(digest).stat().st_mtime_ns == mtime

    def test_deduplicates_identical_bodies(self, store: RawStore) -> None:
        """A docs site that serves the same boilerplate under six URLs stores it once."""
        body = b"same boilerplate"
        digest = content_hash(body)
        for _ in range(6):
            store.put(digest, body)
        assert store.stats()["objects"] == 1

    def test_get_of_an_absent_hash_is_none_not_an_error(self, store: RawStore) -> None:
        """A body pruned by a gc run is a normal state, not an exception: the pipeline
        treats a missing body as "needs refetching"."""
        assert store.get(content_hash(b"never stored")) is None


class TestStats:
    def test_counts_nothing_before_the_root_exists(self, store: RawStore) -> None:
        assert store.stats() == {"objects": 0, "bytes": 0}

    def test_sums_sizes_and_ignores_partials(self, store: RawStore) -> None:
        store.put(content_hash(b"aaa"), b"aaa")
        store.put(content_hash(b"bbbb"), b"bbbb")
        (store.root / "orphan.part").write_bytes(b"junk")
        assert store.stats() == {"objects": 2, "bytes": 7}


class TestPrune:
    def test_keeps_what_is_still_referenced(self, store: RawStore) -> None:
        keep = content_hash(b"live")
        drop = content_hash(b"dead")
        store.put(keep, b"live")
        store.put(drop, b"dead")

        removed = store.prune({keep})

        assert removed == 1
        assert store.exists(keep)
        assert not store.exists(drop)

    def test_removes_orphaned_partials(self, store: RawStore) -> None:
        """A ``.part`` is the residue of a crash mid-write. Its name is not a hash, so
        nothing will ever reference it."""
        keep = content_hash(b"live")
        store.put(keep, b"live")
        (store.root / "aa" / "bb").mkdir(parents=True)
        (store.root / "aa" / "bb" / "deadbeef.part").write_bytes(b"partial")

        assert store.prune({keep}) == 1
        assert store.exists(keep)

    def test_cleans_up_emptied_shards(self, store: RawStore) -> None:
        """Left behind, the shard tree grows monotonically and ``stats`` walks
        directories that can never contain anything again."""
        drop = content_hash(b"dead")
        store.put(drop, b"dead")
        store.prune(set())
        assert not any(path.is_dir() for path in store.root.rglob("*"))

    def test_an_absent_root_prunes_nothing(self, store: RawStore) -> None:
        assert store.prune({"anything"}) == 0

    def test_an_empty_keep_set_deletes_everything(self, store: RawStore) -> None:
        """Honest but dangerous, which is why the pipeline never calls this and the CLI
        wraps it in a refusal: ``gc`` will not prune on an empty live set unless forced,
        because "the table was cleared" and "the bodies are unreferenced" look identical
        from here."""
        store.put(content_hash(b"a"), b"a")
        store.put(content_hash(b"b"), b"b")
        assert store.prune(set()) == 2
        assert store.stats()["objects"] == 0


class TestNuke:
    def test_is_idempotent(self, store: RawStore) -> None:
        store.put(content_hash(b"a"), b"a")
        store.nuke()
        store.nuke()
        assert not store.root.exists()
