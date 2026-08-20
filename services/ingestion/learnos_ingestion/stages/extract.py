"""Extract and validate.

Extraction batches chunks and asks an extractor for candidates. Validation then
tries to build the real schema model out of each candidate payload and records what
went wrong — without discarding anything.

That last part is the important one. A candidate that fails validation is still
written to the review queue, with the failure attached as a ``ValidationIssue``.
Discarding it would leave an operator looking at a source that produced forty
concepts yesterday and eleven today with no way to find out why. The candidates
table exists precisely to hold content the rest of the platform would reject.
"""

from __future__ import annotations

import structlog
from learnos_schema.concept import Concept
from learnos_schema.ingestion import (
    Chunk,
    ExtractionCandidate,
    ExtractionRequest,
    ExtractionTarget,
    IngestionStage,
    StageReport,
    ValidationIssue,
)
from learnos_schema.practice import PracticeTask
from learnos_schema.project import Assessment, Project
from pydantic import TypeAdapter, ValidationError

from ..config import IngestionSettings
from ..extractors import Extractor

log = structlog.get_logger(__name__)

#: Chunks per extractor call. Enough that the model sees a whole section's context,
#: small enough that one bad batch does not cost a large call. Also bounds the
#: blast radius of a parse failure: a batch that produces garbage loses eight
#: chunks' worth of candidates, not a source's worth.
BATCH_SIZE = 8

#: ``PracticeTask`` is a discriminated union over seven kinds, so it needs a
#: ``TypeAdapter`` rather than a ``.model_validate`` classmethod. Built once at
#: import: constructing one per candidate would rebuild the union's validator
#: thousands of times per run.
_PRACTICE_ADAPTER: TypeAdapter[PracticeTask] = TypeAdapter(PracticeTask)

#: Which schema model validates which target. ``Assessment`` lives in ``project``
#: alongside ``Project`` rather than in a module of its own.
VALIDATORS = {
    ExtractionTarget.CONCEPT.value: lambda payload: Concept.model_validate(payload),
    ExtractionTarget.PRACTICE.value: _PRACTICE_ADAPTER.validate_python,
    ExtractionTarget.PROJECT.value: lambda payload: Project.model_validate(payload),
    ExtractionTarget.ASSESSMENT.value: lambda payload: Assessment.model_validate(payload),
}


def _batches(chunks: list[Chunk], size: int) -> list[list[Chunk]]:
    """Group chunks, keeping documents together where possible.

    Chunks arrive ordered by document then ordinal, so slicing preserves locality:
    a batch is usually one section of one page rather than eight unrelated snippets
    from eight pages. That matters for extraction quality — an extractor shown
    contiguous text can tell what the section is about.
    """
    return [chunks[index : index + size] for index in range(0, len(chunks), size)]


async def run_extract(
    chunks: list[Chunk],
    *,
    subject_id: str,
    extractor: Extractor,
    repo,  # IngestionRepository
    settings: IngestionSettings,
    targets: tuple[str, ...] = (ExtractionTarget.CONCEPT.value, ExtractionTarget.PRACTICE.value),
    dry_run: bool = True,
) -> tuple[list[ExtractionCandidate], StageReport]:
    """Run the extractor over every batch, for every requested target."""
    report = StageReport(stage=IngestionStage.EXTRACT, items_in=len(chunks))
    produced: list[ExtractionCandidate] = []

    if not chunks:
        report.messages.append("no changed chunks; nothing to extract")
        return produced, report

    for target in targets:
        existing = await repo.existing_candidate_ids(subject_id, target) if repo is not None else []
        for batch in _batches(chunks, BATCH_SIZE):
            request = ExtractionRequest(
                subject_id=subject_id,
                target=target,
                chunks=batch,
                existing_ids=existing,
            )
            try:
                candidates = await extractor.extract(request)
            except Exception as exc:  # noqa: BLE001
                # One failed batch must not lose the batches already done, so this
                # is recorded and the loop continues.
                report.ok = False
                report.messages.append(f"{target}: batch failed: {type(exc).__name__}: {exc}")
                continue

            for candidate in candidates:
                if candidate.confidence < settings.min_confidence:
                    candidate.issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="low_confidence",
                            message=(
                                f"confidence {candidate.confidence:.2f} is below the "
                                f"{settings.min_confidence:.2f} floor; the extractor was guessing"
                            ),
                        )
                    )
                produced.append(candidate)
                # Track ids within the run too, so two batches describing the same
                # heading do not both mint it.
                payload_id = candidate.payload.get("id")
                if isinstance(payload_id, str):
                    existing.append(payload_id)

    report.items_out = len(produced)
    log.info(
        "extract.done",
        subject=subject_id,
        extractor=extractor.name,
        candidates=len(produced),
        dry_run=dry_run,
    )
    return produced, report


def validate_candidate(candidate: ExtractionCandidate) -> list[ValidationIssue]:
    """Try to build the real model. Returns issues; does not raise.

    Errors here are what keep a candidate out of ``is_promotable``, so this is the
    gate between "a model said something" and "this could become learner-visible".
    """
    validator = VALIDATORS.get(str(candidate.target))
    if validator is None:
        return [
            ValidationIssue(
                severity="warning",
                code="no_validator",
                message=f"no schema validator registered for target {candidate.target!r}",
            )
        ]

    try:
        validator(candidate.payload)
    except ValidationError as exc:
        issues: list[ValidationIssue] = []
        for error in exc.errors():
            pointer = "/" + "/".join(str(part) for part in error["loc"])
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=f"schema.{error['type']}",
                    message=error["msg"],
                    pointer=pointer,
                )
            )
        return issues
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationIssue(severity="error", code="schema.unexpected", message=f"{type(exc).__name__}: {exc}")
        ]

    return []


async def run_validate(
    candidates: list[ExtractionCandidate],
    *,
    repo,  # IngestionRepository
    dry_run: bool = True,
) -> tuple[list[ExtractionCandidate], StageReport]:
    """Validate every candidate and persist it, valid or not."""
    report = StageReport(stage=IngestionStage.VALIDATE, items_in=len(candidates))
    clean = 0
    written = 0

    for candidate in candidates:
        issues = validate_candidate(candidate)
        # Extend rather than replace: the extractor's own issues (empty
        # expected_output, thin explanation, duplicate) are findings a reviewer needs
        # and are not rediscoverable from a schema check.
        candidate.issues.extend(issues)
        if not any(issue.severity == "error" for issue in candidate.issues):
            clean += 1
        if not dry_run and repo is not None:
            if await repo.upsert_candidate(candidate):
                written += 1

    report.items_out = clean
    report.skipped = len(candidates) - clean
    report.messages.append(
        f"{clean} of {len(candidates)} candidates are schema-clean; "
        f"{report.skipped} carry errors and are queued for review with the failure attached"
    )
    if not dry_run:
        report.messages.append(f"{written} newly written, {len(candidates) - written} already present or human-touched")

    log.info("validate.done", total=len(candidates), clean=clean, written=written, dry_run=dry_run)
    return candidates, report
