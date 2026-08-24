"""Adapter policy.

Everything here is a refusal test. The adapter layer is the only place in LearnOS
that reaches outside the deployment, and the four gates in ``SourceAdapter.run``
(licence, robots, rate limit, page cap) are the whole reason that is acceptable.
They live in the base class rather than in each adapter because "every adapter
remembered to check" is not a security property, and these tests exist to keep it
that way as adapters get added.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from learnos_schema.ingestion import AdapterKind, SourceSpec

from learnos_ingestion.adapters import ADAPTERS, for_source
from learnos_ingestion.adapters.base import (
    PERMISSIVE_LICENSES,
    AdapterUnavailable,
    FetchRefused,
    RateLimiter,
    license_gate,
)
from learnos_ingestion.adapters.local import LocalAdapter


def spec(**overrides) -> SourceSpec:
    payload = {
        "id": "test.source",
        "subject_id": "programming.python",
        "title": "Test source",
        "adapter": "local",
        "source_type": "documentation",
        "entrypoint": ".",
        "priority": 50,
        "is_first_party": False,
        "license": None,
        "policy": {},
    }
    payload.update(overrides)
    return SourceSpec.model_validate(payload)


class TestLicenseGate:
    def test_refuses_an_unknown_licence(self) -> None:
        with pytest.raises(FetchRefused, match="license_ack"):
            license_gate(spec(license="All rights reserved"))

    def test_refuses_a_missing_licence(self) -> None:
        """Absent is not permissive. A source with no declared licence is the most
        likely one to be someone's copyrighted book."""
        with pytest.raises(FetchRefused):
            license_gate(spec(license=None))

    def test_allows_a_permissive_licence(self) -> None:
        license_gate(spec(license="MIT"))

    def test_is_case_and_whitespace_insensitive(self) -> None:
        """Licence strings are hand-typed in sources.json."""
        license_gate(spec(license="  Apache-2.0  "))

    def test_first_party_needs_no_acknowledgement(self) -> None:
        # priority 80 because `SourceSpec` refuses a first-party source below it: a
        # blog must not be able to outrank our own docs. Not the property under test,
        # but the model will not build the object without it.
        license_gate(spec(license=None, is_first_party=True, priority=80))

    def test_an_acknowledgement_unblocks_a_reviewed_source(self) -> None:
        license_gate(
            spec(
                license="CC-BY-NC-4.0",
                policy={"license_ack": "reviewed 2026-08: non-commercial use, attribution in SourceRef"},
            )
        )

    def test_allowlist_holds_only_lowercase_entries(self) -> None:
        """``license_gate`` lowercases before comparing, so an uppercase entry here
        would be permanently unreachable and silently stop working."""
        assert all(entry == entry.lower() for entry in PERMISSIVE_LICENSES)


class TestPermits:
    def test_deny_beats_allow(self) -> None:
        adapter = LocalAdapter(
            spec(policy={"allow_patterns": [r"docs/"], "deny_patterns": [r"docs/internal/"]}),
            root=Path("/tmp"),
        )
        assert adapter.permits("/tmp/docs/public/a.md")
        assert not adapter.permits("/tmp/docs/internal/a.md")

    def test_an_empty_allowlist_means_everything_not_denied(self) -> None:
        adapter = LocalAdapter(spec(policy={"deny_patterns": [r"\.git/"]}), root=Path("/tmp"))
        assert adapter.permits("/tmp/anything.md")
        assert not adapter.permits("/tmp/.git/config")

    def test_local_patterns_match_the_relative_path(self) -> None:
        """A deny pattern written as ``tests/`` must behave the same whether the
        checkout is at /app or /home/someone/src."""
        adapter = LocalAdapter(spec(policy={"deny_patterns": ["^tests/"]}), root=Path("/tmp/repo"))
        assert not adapter.permits("/tmp/repo/tests/test_a.md")
        assert adapter.permits("/tmp/repo/docs/tests/test_a.md")


class TestLocalAdapterSandbox:
    def test_refuses_an_entrypoint_that_escapes_the_root(self, tmp_path: Path) -> None:
        """Subject packages are editable content.

        If a path in one were trusted, "add a source" would be equivalent to "read
        any file the ingestion process can read", which includes the environment of
        the one container with outbound network access.
        """
        adapter = LocalAdapter(spec(entrypoint="../../../etc/passwd"), root=tmp_path)
        with pytest.raises(FetchRefused, match="outside"):
            adapter._resolved()

    def test_refuses_an_absolute_escape(self, tmp_path: Path) -> None:
        adapter = LocalAdapter(spec(entrypoint="/etc"), root=tmp_path)
        with pytest.raises(FetchRefused, match="outside"):
            adapter._resolved()

    def test_allows_a_path_inside_the_root(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        adapter = LocalAdapter(spec(entrypoint="docs"), root=tmp_path)
        assert adapter._resolved() == (tmp_path / "docs").resolve()

    async def test_discovery_is_sorted_and_skips_dotfiles(self, tmp_path: Path) -> None:
        """Unstable order makes two runs produce chunk ordinals that disagree, which
        makes the diff report changes that did not happen."""
        for name in ("c.md", "a.md", "b.md"):
            (tmp_path / name).write_text("body", encoding="utf-8")
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "secret.md").write_text("no", encoding="utf-8")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        adapter = LocalAdapter(spec(entrypoint="."), root=tmp_path)
        found = [Path(locator).name async for locator in adapter.discover(None)]
        assert found == ["a.md", "b.md", "c.md"]

    async def test_document_ids_are_relative_so_they_survive_a_move(self, tmp_path: Path) -> None:
        """The id must not contain the absolute path, or moving the checkout would
        make every stored document look deleted and every page look new."""
        (tmp_path / "a.md").write_text("body", encoding="utf-8")
        adapter = LocalAdapter(spec(entrypoint="."), root=tmp_path)
        document = await adapter.fetch_one(None, str(tmp_path / "a.md"))
        assert document is not None
        assert document.path == "a.md"
        assert str(tmp_path) not in document.id


class TestRateLimiter:
    async def test_enforces_a_minimum_interval(self) -> None:
        """A strict interval, not a token bucket.

        A bucket would permit a burst, which is the one thing a crawler must not do to
        someone else's docs site, and the thing that gets an IP blocked.
        """
        limiter = RateLimiter(rps=20.0)  # 50ms interval
        await limiter.wait()
        start = time.monotonic()
        await limiter.wait()
        assert time.monotonic() - start >= 0.04

    async def test_serialises_concurrent_waiters(self) -> None:
        limiter = RateLimiter(rps=50.0)  # 20ms
        start = time.monotonic()
        await asyncio.gather(*(limiter.wait() for _ in range(4)))
        assert time.monotonic() - start >= 0.05


class TestRegistry:
    def test_every_adapter_kind_is_registered(self) -> None:
        """A kind with no adapter is a source that validates and then does nothing."""
        assert {kind.value for kind in AdapterKind} == set(ADAPTERS)

    def test_registry_is_keyed_by_value_not_member(self) -> None:
        """``SchemaModel`` sets ``use_enum_values=True``, so ``spec.adapter`` is a
        plain string. A registry keyed by enum member would miss every lookup."""
        assert all(isinstance(key, str) for key in ADAPTERS)

    def test_for_source_rejects_an_unknown_kind(self) -> None:
        broken = spec()
        object.__setattr__(broken, "adapter", "telepathy")
        with pytest.raises(AdapterUnavailable):
            for_source(broken)

    def test_for_source_threads_the_root_into_the_local_adapter(self, tmp_path: Path) -> None:
        """Constructed without a root, ``LocalAdapter`` sandboxes to the process cwd,
        which in the ingestion container is /app, i.e. everything."""
        adapter = for_source(spec(adapter="local"), local_root=tmp_path)
        assert isinstance(adapter, LocalAdapter)
        assert adapter.root == tmp_path.resolve()
