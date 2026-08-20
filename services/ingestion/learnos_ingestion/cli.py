"""``learnos-ingest`` — the operator interface to the pipeline.

The pipeline is a CLI rather than a service, and that is a deliberate boundary. The
one process in this system with outbound network access is the one an operator starts
by hand, with arguments they chose, against sources they registered. There is no HTTP
route that makes the platform fetch a URL, so there is no route to abuse into
fetching an internal one.

Two properties matter more than the command list:

**Nothing writes without ``--commit``.** Every command that could change state
defaults to a dry run and prints what it would do. This is not timidity — a crawl is
the one operation here that is visible to a third party and slow to undo.

**``publish`` is not a command.** ``build`` writes files into a subject package;
content becomes learner-visible when an admin reloads the registry, which is a
separate, audited action in the API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from learnos_schema.ingestion import AdapterKind, SourceSpec

from .config import IngestionSettings, get_settings
from .db import session_scope
from .pipeline import DEFAULT_STAGES, STAGE_ORDER, Pipeline
from .storage import IngestionRepository, RawStore


def _echo(*lines: str) -> None:
    for line in lines:
        print(line)


# ---------------------------------------------------------------------------
# sources: package registry entry -> crawler spec
# ---------------------------------------------------------------------------


def infer_adapter(entry: dict) -> str:
    """Pick an adapter for a ``sources.json`` entry.

    ``SourceRegistryEntry`` — what a content author writes and what a concept's
    citations point at — has no adapter field, on purpose: an author is describing
    *what they trust*, not *how to crawl it*. The mapping lives here so that adding a
    source to a package stays a content decision.

    The inference is intentionally shallow and always beatable by declaring
    ``adapter`` explicitly in the entry. A wrong guess is visible immediately (the
    fetch stage reports zero documents), whereas a clever guess that silently picks
    ``sitemap`` for a site whose sitemap is stale would produce a crawl that looks
    fine and misses half the pages.
    """
    declared = entry.get("adapter")
    if isinstance(declared, str) and declared in {kind.value for kind in AdapterKind}:
        return declared

    url = str(entry.get("base_url") or "")
    lowered = url.lower()
    if not url:
        return AdapterKind.LOCAL.value
    if "github.com" in lowered:
        return AdapterKind.GITHUB.value
    if lowered.endswith(".pdf"):
        return AdapterKind.PDF.value
    if lowered.endswith((".json", ".yaml", ".yml")):
        return AdapterKind.OPENAPI.value
    if lowered.endswith(("sitemap.xml", "sitemap_index.xml")):
        return AdapterKind.SITEMAP.value
    if lowered.endswith((".rss", ".atom", "/feed", "/feed/", "feed.xml")):
        return AdapterKind.RSS.value
    if str(entry.get("source_type")) == "repository":
        return AdapterKind.GITHUB.value
    return AdapterKind.WEB.value


def spec_from_entry(entry: dict, *, subject_id: str) -> SourceSpec:
    """Translate one ``sources.json`` entry into a ``SourceSpec``.

    The policy is assembled from the entry's ``respect_robots`` and
    ``rate_limit_rps`` and nothing else. In particular ``license_ack`` is never
    synthesised here: a non-permissive licence has to be acknowledged by a human
    editing the source row, and generating the acknowledgement from the presence of a
    licence string would defeat the entire check.
    """
    policy = {
        "respect_robots": bool(entry.get("respect_robots", True)),
        "rate_limit_rps": float(entry.get("rate_limit_rps", 0.5)),
    }
    for key in ("max_pages", "max_depth", "allow_patterns", "deny_patterns", "license_ack", "user_agent"):
        if key in entry:
            policy[key] = entry[key]

    return SourceSpec.model_validate(
        {
            "id": entry["id"],
            "subject_id": subject_id,
            "title": entry.get("title") or entry["id"],
            "adapter": infer_adapter(entry),
            "source_type": entry.get("source_type", "documentation"),
            "entrypoint": entry.get("entrypoint") or entry.get("base_url") or ".",
            "priority": int(entry.get("priority", 50)),
            "is_first_party": bool(entry.get("is_first_party", False)),
            "license": entry.get("license"),
            "policy": policy,
            "notes": entry.get("notes"),
        }
    )


def _load_package_sources(subject_dir: Path) -> tuple[str, list[dict]]:
    manifest_path = subject_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"no manifest.json in {subject_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    subject_id = manifest.get("id") or manifest.get("subject_id")
    if not subject_id:
        raise SystemExit(f"{manifest_path} has no subject id")

    sources_path = subject_dir / manifest.get("sources_file", "sources.json")
    if not sources_path.is_file():
        raise SystemExit(f"no {sources_path.name} in {subject_dir}")
    raw = json.loads(sources_path.read_text(encoding="utf-8"))
    entries = raw.get("sources", raw) if isinstance(raw, dict) else raw
    return str(subject_id), list(entries)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


async def cmd_sources_sync(args: argparse.Namespace, settings: IngestionSettings) -> int:
    subject_dir = Path(args.subject_dir).resolve()
    subject_id, entries = _load_package_sources(subject_dir)

    specs: list[SourceSpec] = []
    problems: list[str] = []
    for entry in entries:
        try:
            specs.append(spec_from_entry(entry, subject_id=subject_id))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{entry.get('id', '<no id>')}: {type(exc).__name__}: {exc}")

    _echo(f"{subject_id}: {len(specs)} sources readable, {len(problems)} rejected")
    for spec in specs:
        _echo(f"  {spec.priority:3d}  {str(spec.adapter):8s} {spec.id:38s} {spec.entrypoint}")
    for problem in problems:
        _echo(f"  !! {problem}")

    if not args.commit:
        _echo("", "dry run: nothing written. Re-run with --commit to register these sources.")
        return 0 if not problems else 1

    async with session_scope(settings) as session:
        repo = IngestionRepository(session)
        for spec in specs:
            await repo.upsert_source(spec)
        await session.commit()
    _echo("", f"registered {len(specs)} sources for {subject_id}")
    return 0 if not problems else 1


async def cmd_sources_list(args: argparse.Namespace, settings: IngestionSettings) -> int:
    async with session_scope(settings) as session:
        specs = await IngestionRepository(session).sources_for(args.subject)
    if not specs:
        _echo(f"no enabled sources for {args.subject}. Run 'learnos-ingest sources sync <dir> --commit' first.")
        return 1
    for spec in specs:
        party = "1st" if spec.is_first_party else "3rd"
        _echo(
            f"{spec.priority:3d}  {party}  {str(spec.adapter):8s} {spec.id:38s} "
            f"{spec.license or '-':14s} {spec.entrypoint}"
        )
    return 0


async def cmd_run(args: argparse.Namespace, settings: IngestionSettings) -> int:
    stages = tuple(args.stage) if args.stage else DEFAULT_STAGES
    unknown = [stage for stage in stages if stage not in STAGE_ORDER]
    if unknown:
        _echo(f"unknown stage(s): {', '.join(unknown)}", f"valid stages: {', '.join(STAGE_ORDER)}")
        return 2

    async with session_scope(settings) as session:
        pipeline = Pipeline(session, settings=settings)
        result = await pipeline.run(
            args.subject,
            source_ids=args.source or None,
            stages=stages,
            dry_run=not args.commit,
            subject_dir=Path(args.subject_dir).resolve() if args.subject_dir else None,
        )

    _echo(*result.summary_lines())
    if not args.commit:
        _echo("", "dry run: nothing was written. Re-run with --commit to persist.")
    return 0 if result.ok else 1


async def cmd_status(args: argparse.Namespace, settings: IngestionSettings) -> int:
    store = RawStore(settings.raw_dir)
    async with session_scope(settings) as session:
        counts = await IngestionRepository(session).counts(args.subject)
    stats = store.stats()
    _echo(
        f"{args.subject}",
        f"  sources        {counts['sources']}",
        f"  documents      {counts['documents']}",
        f"  chunks         {counts['chunks']}",
        f"  candidates     {counts['candidates']}",
        f"  pending review {counts['pending_review']}",
        f"  raw store      {stats['objects']} objects, {stats['bytes'] / 1_048_576:.1f} MiB",
    )
    return 0


async def cmd_review(args: argparse.Namespace, settings: IngestionSettings) -> int:
    async with session_scope(settings) as session:
        rows = await IngestionRepository(session).candidates_for_review(
            args.subject, status=args.status, limit=args.limit
        )
        if not rows:
            _echo(f"nothing with status {args.status!r} for {args.subject}")
            return 0
        for row in rows:
            payload = row.payload or {}
            errors = [issue for issue in (row.issues or []) if issue.get("severity") == "error"]
            flag = f"  {len(errors)} ERROR" if errors else ""
            _echo(
                f"{row.id}",
                f"  {row.target:10s} conf {row.confidence:.2f}{flag}",
                f"  id:    {payload.get('id', '<none>')}",
                f"  title: {payload.get('title', '<none>')}",
                f"  cites: {len(row.chunk_ids or [])} chunks",
            )
            for issue in (row.issues or [])[: args.issues]:
                _echo(f"    [{issue.get('severity')}] {issue.get('code')}: {issue.get('message')}")
            _echo("")
    return 0


async def cmd_decide(args: argparse.Namespace, settings: IngestionSettings) -> int:
    """Shared implementation for ``approve`` and ``reject``."""
    status = "approved" if args.action == "approve" else "rejected"
    if not args.commit:
        _echo(
            f"dry run: would set {len(args.candidate)} candidate(s) to {status} on behalf of {args.by}",
            *(f"  {candidate_id}" for candidate_id in args.candidate),
            "",
            "Re-run with --commit. Note that approving does not publish: the build stage",
            "folds approved candidates into the package, and an admin reload makes them live.",
        )
        return 0

    async with session_scope(settings) as session:
        repo = IngestionRepository(session)
        changed = await repo.set_candidate_status(
            args.candidate, status, reviewed_by=args.by, note=args.reason
        )
        await session.commit()

    missing = set(args.candidate) - set(changed)
    _echo(f"{len(changed)} candidate(s) set to {status}")
    for candidate_id in sorted(missing):
        _echo(f"  !! not found: {candidate_id}")
    return 0 if not missing else 1


async def cmd_gc(args: argparse.Namespace, settings: IngestionSettings) -> int:
    store = RawStore(settings.raw_dir)
    async with session_scope(settings) as session:
        live = await IngestionRepository(session).live_content_hashes()

    stats = store.stats()
    if not live:
        # An empty live set with a non-empty store means the documents table was
        # truncated, not that every body is garbage. Deleting here would destroy a
        # crawl that a re-import could otherwise recover.
        _echo(
            f"refusing to prune: the documents table reports zero live hashes while the store holds "
            f"{stats['objects']} objects. That combination means the table was cleared, not that the "
            f"bodies are unreferenced. Use 'learnos-ingest gc --force' if you really mean it."
        )
        if not args.force:
            return 1

    if not args.commit:
        _echo(
            f"dry run: {stats['objects']} objects on disk, {len(live)} referenced by a document row.",
            "Re-run with --commit to delete the difference.",
        )
        return 0

    removed = store.prune(live)
    _echo(f"removed {removed} unreferenced object(s)")
    return 0


async def cmd_doctor(args: argparse.Namespace, settings: IngestionSettings) -> int:
    """Check the things that make a first run fail, before it fails slowly."""
    ok = True
    ready, detail = settings.extractor_ready()
    _echo(
        "configuration",
        f"  env              {settings.env}",
        f"  database         {settings.database_url.split('@')[-1]}",
        f"  subjects_dir     {settings.subjects_dir}  {'(exists)' if settings.subjects_dir.is_dir() else '(MISSING)'}",
        f"  storage_dir      {settings.storage_dir}",
        f"  extractor        {detail}",
        f"  chunking         {settings.chunk_target_tokens} target / {settings.chunk_overlap_tokens} overlap",
        f"  concurrency      {settings.max_concurrent_fetches}",
    )
    if not settings.subjects_dir.is_dir():
        ok = False
    if not ready:
        ok = False

    try:
        async with session_scope(settings) as session:
            await IngestionRepository(session).ping()
        _echo("  database         reachable")
    except Exception as exc:  # noqa: BLE001
        ok = False
        _echo(f"  database         UNREACHABLE: {type(exc).__name__}: {exc}")

    missing = [
        name
        for name, module in (("bs4", "bs4"), ("lxml", "lxml"), ("httpx", "httpx"))
        if not _importable(module)
    ]
    if missing:
        ok = False
        _echo(f"  parsers          MISSING: {', '.join(missing)} — HTML sources will be skipped")
    else:
        _echo("  parsers          bs4 + lxml present")

    _echo("", "ok" if ok else "problems found")
    return 0 if ok else 1


def _importable(name: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="learnos-ingest",
        description="LearnOS ingestion pipeline: internet sources into a Subject Package.",
        epilog=(
            "Every state-changing command is a dry run unless given --commit. "
            "There is no 'publish' command: build writes the package, and an admin "
            "reload in the API makes it live."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run the pipeline over a subject's sources")
    run.add_argument("subject", help="subject id, e.g. programming.python")
    run.add_argument("--source", action="append", help="limit to this source id (repeatable)")
    run.add_argument(
        "--stage",
        action="append",
        help=(
            f"stage to run (repeatable). Any gap between the first and last is filled in, "
            f"because a later stage cannot run on stale input. Order: {' -> '.join(STAGE_ORDER)}"
        ),
    )
    run.add_argument("--subject-dir", help="package directory for the build stage (default: found by manifest id)")
    run.add_argument("--commit", action="store_true", help="actually write")
    run.set_defaults(handler=cmd_run)

    sources = subparsers.add_parser("sources", help="register and inspect crawl sources")
    source_subs = sources.add_subparsers(dest="sources_command", required=True)

    sync = source_subs.add_parser("sync", help="register a package's sources.json into the database")
    sync.add_argument("subject_dir", help="path to a subject package directory")
    sync.add_argument("--commit", action="store_true", help="actually write")
    sync.set_defaults(handler=cmd_sources_sync)

    listing = source_subs.add_parser("list", help="show registered sources for a subject")
    listing.add_argument("subject")
    listing.set_defaults(handler=cmd_sources_list)

    status = subparsers.add_parser("status", help="row counts and store size for a subject")
    status.add_argument("subject")
    status.set_defaults(handler=cmd_status)

    review = subparsers.add_parser("review", help="show the candidate review queue")
    review.add_argument("subject")
    review.add_argument("--status", default="draft", choices=["draft", "in_review", "approved", "rejected", "published"])
    review.add_argument("--limit", type=int, default=20)
    review.add_argument("--issues", type=int, default=3, help="issues to print per candidate")
    review.set_defaults(handler=cmd_review)

    for action in ("approve", "reject"):
        decide = subparsers.add_parser(action, help=f"{action} one or more candidates")
        decide.add_argument("candidate", nargs="+", help="candidate row ids")
        decide.add_argument("--by", required=True, help="reviewer identity, stamped into provenance")
        decide.add_argument("--reason", help="free-text note kept with the decision")
        decide.add_argument("--commit", action="store_true", help="actually write")
        decide.set_defaults(handler=cmd_decide, action=action)

    gc = subparsers.add_parser("gc", help="delete raw bodies no document row references")
    gc.add_argument("--commit", action="store_true", help="actually delete")
    gc.add_argument("--force", action="store_true", help="prune even when the live set is empty")
    gc.set_defaults(handler=cmd_gc)

    doctor = subparsers.add_parser("doctor", help="check configuration, database and parser availability")
    doctor.set_defaults(handler=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    from .logging import configure_logging

    configure_logging(settings)

    try:
        return asyncio.run(args.handler(args, settings))
    except KeyboardInterrupt:
        # Interrupting a crawl is normal and safe: every write is an upsert keyed on
        # a content-derived id, so the next run re-fetches nothing it already stored.
        _echo("", "interrupted. Re-running resumes: stored documents are skipped by hash.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
