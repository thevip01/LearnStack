"""Admin-side ingestion: source registry, run ledger, review queue, provenance.

Separate from the ingestion *pipeline* (``services/ingestion``) on purpose. This
package reads and writes the five ingestion tables and nothing else: it never
fetches a URL, never calls a model, never spends a request thread on a crawl. That
split is what lets the pipeline hold outbound credentials and network egress while
the process serving learner traffic holds neither.
"""

from __future__ import annotations

from .service import (
    CANDIDATE_TARGETS,
    DECISION_STATUS,
    RUNNABLE_STAGES,
    candidate_id_for,
    candidate_row_to_dict,
    create_run,
    get_run,
    list_candidates,
    list_runs,
    list_sources,
    provenance_trail,
    review_candidate,
    run_row_to_dict,
    source_row_to_dict,
    upsert_source,
)

__all__ = [
    "CANDIDATE_TARGETS",
    "DECISION_STATUS",
    "RUNNABLE_STAGES",
    "candidate_id_for",
    "candidate_row_to_dict",
    "create_run",
    "get_run",
    "list_candidates",
    "list_runs",
    "list_sources",
    "provenance_trail",
    "review_candidate",
    "run_row_to_dict",
    "source_row_to_dict",
    "upsert_source",
]
