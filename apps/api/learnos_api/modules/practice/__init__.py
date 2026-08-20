"""Practice: grading, attempts and the submission pipeline.

Import from here rather than from the per-kind modules. The kind-specific graders
are an implementation detail; ``submit`` is the contract.
"""

from __future__ import annotations

from .attempts import (
    attempt_out,
    attempt_stats,
    elapsed_ms,
    has_passed,
    hint_ladder,
    latest_attempts,
    load_attempt,
    open_attempt,
    record_submission,
    reveal_hint,
    revealed_hints,
    submission_history,
)
from .code import build_workspace, protected_paths, test_specs
from .design import grade_architecture, grade_incident
from .pipeline import mastery_deltas, newly_unlocked, reveal_for, submit, task_kind
from .quiz import grade_quiz, normalise_text
from .results import GradeOutcome, decide, weighted_fraction
from .sql import grade_sql
from .terminal import grade_terminal

__all__ = [
    "GradeOutcome",
    "attempt_out",
    "attempt_stats",
    "build_workspace",
    "decide",
    "elapsed_ms",
    "grade_architecture",
    "grade_incident",
    "grade_quiz",
    "grade_sql",
    "grade_terminal",
    "has_passed",
    "hint_ladder",
    "latest_attempts",
    "load_attempt",
    "mastery_deltas",
    "newly_unlocked",
    "normalise_text",
    "open_attempt",
    "protected_paths",
    "record_submission",
    "reveal_for",
    "reveal_hint",
    "revealed_hints",
    "submission_history",
    "submit",
    "task_kind",
    "test_specs",
    "weighted_fraction",
]
