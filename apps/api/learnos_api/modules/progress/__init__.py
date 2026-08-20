"""Progress: evidence, rollup, adaptive state and recommendations."""

from __future__ import annotations

from .context import (
    adaptive_state,
    learner_view,
    log_concept_view,
    passed_task_ids,
    recent_events,
    viewed_concept_ids,
)
from .evidence import (
    difficulty_weight,
    evidence_for_task,
    evidence_rows_for_skill,
    load_evidence,
    persist_evidence,
)
from .recommender import LearnerView, next_up, recommend
from .rollup import (
    DIMENSION_ORDER,
    apply_attempt_outcome,
    catalog_snapshot,
    compute_progress,
    get_progress,
    history,
    invalidate,
    mastery_lookup,
    masteries_from_evidence,
    sync_skill_states,
)

__all__ = [
    "DIMENSION_ORDER",
    "LearnerView",
    "adaptive_state",
    "apply_attempt_outcome",
    "catalog_snapshot",
    "compute_progress",
    "difficulty_weight",
    "evidence_for_task",
    "evidence_rows_for_skill",
    "get_progress",
    "history",
    "invalidate",
    "learner_view",
    "load_evidence",
    "log_concept_view",
    "masteries_from_evidence",
    "mastery_lookup",
    "next_up",
    "passed_task_ids",
    "persist_evidence",
    "recent_events",
    "recommend",
    "sync_skill_states",
    "viewed_concept_ids",
]
