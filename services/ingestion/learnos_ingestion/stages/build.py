"""Build: approved candidates into a Subject Package on disk.

The only stage that writes content a learner will see, and the only one that runs
offline against the filesystem rather than the network. Three rules govern it, and
all three exist because the alternative silently destroys authored work.

**Only ``approved`` candidates are folded in.** Not ``draft``, not ``published``.
Draft has not been reviewed. Published is already in the package, and re-folding it
would overwrite whatever an author has edited by hand since, which is the normal
workflow, since a reviewer approves a rough concept and then improves it in the file.

**Existing files are never silently overwritten.** A candidate whose id already
exists on disk is written to a ``.incoming.json`` sidecar and reported, not merged.
Automatic merging of generated content over hand-edited content is how a platform
loses a week of authoring to a crawl nobody was watching.

**The package is validated before the version is bumped.** A build that produces an
invalid package leaves the version and the candidate statuses alone, so nothing
downstream believes the new content loaded. The API's ``registry.reload()`` reads
from disk and would otherwise happily serve a package with dangling references.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog
from learnos_schema.ingestion import IngestionStage, StageReport
from learnos_schema.package import PackageValidationError, load_subject_package

log = structlog.get_logger(__name__)

#: ``ExtractionTarget`` -> the manifest field naming its directory. Practice,
#: projects and assessments all land in their declared directory; curriculum is
#: absent because it is a single file describing module order, and folding a
#: generated fragment into it would reorder a human's curriculum.
TARGET_DIRS = {
    "concept": "concepts_dir",
    "practice": "practice_dir",
    "project": "projects_dir",
    "assessment": "assessments_dir",
}


@dataclass
class BuildResult:
    written: list[str] = field(default_factory=list)
    #: Candidate ids whose target file already exists; parked as sidecars.
    parked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    version_before: str | None = None
    version_after: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def next_version(current: str, *, today: datetime | None = None) -> str:
    """Bump a calendar version: ``2026.08.0`` -> ``2026.08.1``, or roll the month.

    Calendar versioning rather than semver because a subject package has no API to
    break. What a consumer wants to know is how fresh the content is, which a date
    answers and ``1.4.2`` does not.
    """
    now = today or datetime.now(timezone.utc)
    prefix = f"{now.year}.{now.month:02d}"
    if current.startswith(prefix + "."):
        try:
            patch = int(current.rsplit(".", 1)[1])
        except (IndexError, ValueError):
            patch = 0
        return f"{prefix}.{patch + 1}"
    return f"{prefix}.0"


def _slug_for(payload_id: str) -> str:
    """Filename for a payload id.

    The id itself, so a file is findable by grep from a concept reference. Dots are
    kept: ``python.functions.closures.json`` sorts next to its siblings, which
    matters when a subject has ninety concept files.
    """
    return f"{payload_id}.json"


def build_package(
    *,
    subject_dir: Path,
    candidates: list,  # list[CandidateRow], untyped to avoid importing API models here
    dry_run: bool = True,
    bump_version: bool = True,
) -> tuple[BuildResult, StageReport]:
    """Fold approved candidates into the package at ``subject_dir``."""
    report = StageReport(stage=IngestionStage.BUILD, items_in=len(candidates))
    result = BuildResult()

    manifest_path = subject_dir / "manifest.json"
    if not manifest_path.is_file():
        result.errors.append(f"no manifest.json at {subject_dir}")
        report.ok = False
        report.messages.extend(result.errors)
        return result, report

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result.version_before = manifest.get("version")

    for row in candidates:
        target = str(row.target)
        dir_field = TARGET_DIRS.get(target)
        if dir_field is None:
            result.skipped.append(row.id)
            report.messages.append(
                f"{row.id}: target {target!r} has no package directory; curriculum changes are made by hand"
            )
            continue

        payload = row.payload or {}
        payload_id = payload.get("id")
        if not isinstance(payload_id, str) or not payload_id:
            result.errors.append(f"{row.id}: approved candidate has no payload id")
            continue

        directory = subject_dir / manifest.get(dir_field, target + "s")
        destination = directory / _slug_for(payload_id)

        if destination.exists():
            # Parked, not merged. See the module docstring: a generated file
            # overwriting a hand-edited one is unrecoverable, and a sidecar the
            # author can diff is the only safe way to surface an update.
            parked_path = destination.with_suffix(".incoming.json")
            result.parked.append(row.id)
            report.messages.append(
                f"{payload_id}: already exists on disk; wrote {parked_path.name} for review rather than overwriting"
            )
            if not dry_run:
                directory.mkdir(parents=True, exist_ok=True)
                parked_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            continue

        result.written.append(row.id)
        if not dry_run:
            directory.mkdir(parents=True, exist_ok=True)
            # sort_keys so a regenerated file diffs cleanly against its predecessor
            # instead of showing every key as moved.
            destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report.items_out = len(result.written)

    if dry_run:
        report.messages.append(
            f"dry run: would write {len(result.written)}, park {len(result.parked)}, skip {len(result.skipped)}"
        )
        return result, report

    # Validate what is now on disk before touching the version. A package that fails
    # here has already had its files written, which is intentional (an author needs
    # to see the broken file to fix it), but the version stays put so the API does
    # not treat it as a new release.
    try:
        package = load_subject_package(subject_dir, validate=True)
    except PackageValidationError as exc:
        result.errors.append(f"package invalid after build, version not bumped: {exc}")
        report.ok = False
        report.messages.extend(result.errors)
        return result, report
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"package failed to load after build: {type(exc).__name__}: {exc}")
        report.ok = False
        report.messages.extend(result.errors)
        return result, report

    if bump_version and result.written:
        result.version_after = next_version(str(result.version_before or "2026.01.0"))
        manifest["version"] = result.version_after
        # content_hash is recomputed from the loaded package rather than carried
        # forward: a stale hash is what the admin validate route reports as drift,
        # and shipping one here would light that warning on every build.
        try:
            manifest["content_hash"] = package.compute_content_hash()
        except Exception:  # noqa: BLE001
            manifest.pop("content_hash", None)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report.messages.append(f"version {result.version_before} -> {result.version_after}")
    else:
        result.version_after = result.version_before

    log.info(
        "build.done",
        subject_dir=str(subject_dir),
        written=len(result.written),
        parked=len(result.parked),
        version=result.version_after,
    )
    return result, report


async def run_build(
    *,
    subject_id: str,
    subject_dir: Path,
    repo,  # IngestionRepository
    dry_run: bool = True,
) -> tuple[BuildResult, StageReport]:
    """Load approved candidates and fold them in."""
    candidates = await repo.approved_candidates(subject_id)
    result, report = build_package(subject_dir=subject_dir, candidates=candidates, dry_run=dry_run)

    if not dry_run and result.ok and result.written:
        # Marked published only after the package validated. Marking earlier would
        # leave candidates recorded as shipped while the package that was supposed
        # to contain them failed to load.
        await repo.mark_published(result.written)
        report.messages.append(f"marked {len(result.written)} candidates published")

    return result, report
