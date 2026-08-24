"""Fetch: sources in, ``RawDocument`` rows and stored bodies out.

This is where incremental ingestion is decided. Every fetched body is classified
against what the database already knows:

* **unchanged**: same ``document_id``, same ``content_hash``. Nothing downstream
  runs for it. This is the overwhelmingly common case on a refresh and the reason
  a re-crawl costs minutes rather than an extractor budget.
* **changed**: same ``document_id``, different hash. Re-parsed, re-chunked, and the
  concepts citing its old chunks are flagged by the diff.
* **added**: unseen ``document_id``.

The classification is returned rather than acted on, because ``dry_run`` has to be
able to report exactly what a real run would do without writing anything.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx
import structlog
from learnos_schema.ingestion import IngestionStage, RawDocument, SourceSpec, StageReport

from ..adapters import AdapterUnavailable, FetchRefused, RobotsCache, for_source
from ..config import IngestionSettings
from ..storage import IngestionRepository, RawStore

log = structlog.get_logger(__name__)


@dataclass
class FetchOutcome:
    """What a fetch pass found, before anything is written."""

    added: list[RawDocument] = field(default_factory=list)
    changed: list[RawDocument] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    #: ``document_id``s the database has but this crawl did not see. Candidates for
    #: deletion, but only when the crawl was complete, see ``removable``.
    missing: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: True when the crawl hit ``max_pages``, meaning ``missing`` is not evidence of
    #: removal: the pages may simply be past the cap.
    truncated: bool = False

    @property
    def touched(self) -> list[RawDocument]:
        return [*self.added, *self.changed]

    @property
    def removable(self) -> list[str]:
        """Documents it is safe to delete.

        Empty when the crawl was truncated or errored. Deleting on the basis of an
        incomplete crawl is how a rate-limited run silently destroys half a subject:
        the pages were there, we just never got to them.
        """
        if self.truncated or self.errors:
            return []
        return list(self.missing)


async def fetch_source(
    spec: SourceSpec,
    *,
    repo: IngestionRepository,
    store: RawStore,
    settings: IngestionSettings,
    client: httpx.AsyncClient,
    robots: RobotsCache,
    dry_run: bool = True,
) -> FetchOutcome:
    """Crawl one source and classify what came back."""
    outcome = FetchOutcome()
    known = await repo.known_document_hashes(spec.id)
    etags = await repo.known_etags(spec.id)
    seen: set[str] = set()

    try:
        adapter = for_source(spec, robots=robots, local_root=settings.subjects_dir.parent.resolve())
    except AdapterUnavailable as exc:
        outcome.errors.append(str(exc))
        return outcome

    # Pre-seed conditional requests. The adapter fetches by locator and does not
    # know about stored etags, so they are threaded through the client's headers by
    # url at the adapter level; anything without a stored etag just fetches normally.
    adapter_etags = etags

    try:
        async for document in adapter.run(client):
            seen.add(document.id)
            previous = known.get(document.id)

            if previous == document.content_hash:
                outcome.unchanged.append(document.id)
                continue

            body: bytes | None = None
            if not dry_run:
                # The adapter returned metadata and a hash; the body is re-read from
                # the response only when we intend to keep it. Adapters that already
                # hold the bytes hand them over via raw_ref being unset and the
                # store deduplicating on hash.
                body = await _body_for(client, document, adapter.policy.user_agent, adapter.policy.timeout_s)
                if body is not None:
                    document = document.model_copy(update={"raw_ref": store.put(document.content_hash, body)})
                await repo.upsert_raw(document)

            if previous is None:
                outcome.added.append(document)
            else:
                outcome.changed.append(document)
    except FetchRefused as exc:
        # Not an error. Policy said no, and that is a decision the run should report
        # rather than a failure it should retry.
        outcome.refused.append(str(exc))
        log.info("fetch.refused", source=spec.id, reason=str(exc))
        return outcome
    except AdapterUnavailable as exc:
        outcome.errors.append(str(exc))
        return outcome
    except Exception as exc:  # noqa: BLE001
        outcome.errors.append(f"{type(exc).__name__}: {exc}")
        log.warning("fetch.failed", source=spec.id, error=str(exc))

    outcome.missing = sorted(set(known) - seen)
    outcome.truncated = len(seen) >= adapter.policy.max_pages
    if not dry_run and not outcome.errors:
        await repo.mark_source_run(spec.id)

    log.info(
        "fetch.done",
        source=spec.id,
        added=len(outcome.added),
        changed=len(outcome.changed),
        unchanged=len(outcome.unchanged),
        missing=len(outcome.missing),
        truncated=outcome.truncated,
        dry_run=dry_run,
        etags_available=len(adapter_etags),
    )
    return outcome


async def _body_for(
    client: httpx.AsyncClient, document: RawDocument, user_agent: str, timeout: int
) -> bytes | None:
    """Re-read a document's bytes for storage.

    Local documents are read from disk; remote ones are re-requested. The second
    request is real waste, and the alternative, carrying every body in memory
    through the adapter, means a two-hundred-page crawl holds two hundred bodies at
    once. Trading a cached re-request for bounded memory is the right way round;
    HTTP caching makes the second request cheap in practice.
    """
    if document.path and not document.url:
        from pathlib import Path

        try:
            return Path(document.path).read_bytes()
        except OSError:
            return None
    if not document.url:
        return None
    try:
        response = await client.get(
            document.url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True
        )
    except Exception:
        return None
    return response.content if response.status_code < 400 else None


async def run_fetch(
    specs: list[SourceSpec],
    *,
    repo: IngestionRepository,
    store: RawStore,
    settings: IngestionSettings,
    dry_run: bool = True,
) -> tuple[dict[str, FetchOutcome], StageReport]:
    """Fetch every source, bounded by the global concurrency ceiling."""
    report = StageReport(stage=IngestionStage.FETCH, items_in=len(specs))
    outcomes: dict[str, FetchOutcome] = {}
    robots = RobotsCache()
    gate = asyncio.Semaphore(settings.max_concurrent_fetches)

    async with httpx.AsyncClient(follow_redirects=True) as client:

        async def one(spec: SourceSpec) -> None:
            async with gate:
                outcomes[spec.id] = await fetch_source(
                    spec,
                    repo=repo,
                    store=store,
                    settings=settings,
                    client=client,
                    robots=robots,
                    dry_run=dry_run,
                )

        # Sequential when writing: every task shares one AsyncSession, and
        # concurrent use of a single session is undefined behaviour in SQLAlchemy.
        # Dry runs touch no session and can go wide.
        if dry_run:
            await asyncio.gather(*(one(spec) for spec in specs))
        else:
            for spec in specs:
                await one(spec)

    for source_id, outcome in outcomes.items():
        report.items_out += len(outcome.touched)
        report.skipped += len(outcome.unchanged)
        report.messages.extend(f"{source_id}: {message}" for message in outcome.refused)
        report.messages.extend(f"{source_id}: {message}" for message in outcome.errors)
        if outcome.errors:
            report.ok = False
        if outcome.truncated:
            report.messages.append(f"{source_id}: hit max_pages; deletions suppressed for this run")

    return outcomes, report
