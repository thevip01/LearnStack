"""SQLAlchemy models.

Importing this package is what registers every table on ``Base.metadata``, which
both ``create_all`` and Alembic autogenerate depend on. Add a new module here or
its table will silently not exist.
"""

from __future__ import annotations

from .base import ID_LEN, Base, JSONVariant, TimestampMixin, UuidType, uuid_pk
from .execution import Execution
from .ingestion import (
    IngestionCandidate,
    IngestionChunk,
    IngestionDocument,
    IngestionRun,
    IngestionSource,
)
from .practice import ATTEMPT_STATES, Attempt, HintReveal, Submission
from .progress import (
    EVENT_ASSESSMENT_COMPLETED,
    EVENT_CONCEPT_VIEWED,
    EVENT_HINT_TAKEN,
    EVENT_PRACTICE_PASSED,
    EVENT_PRACTICE_SUBMITTED,
    EVENT_PROJECT_COMPLETED,
    MasteryEvidence,
    ProgressEvent,
    UserSkillState,
)
from .search import ConceptIndex
from .user import SubjectVersion, User, UserSubjectEnrollment

__all__ = [
    "ATTEMPT_STATES",
    "Attempt",
    "Base",
    "ConceptIndex",
    "EVENT_ASSESSMENT_COMPLETED",
    "EVENT_CONCEPT_VIEWED",
    "EVENT_HINT_TAKEN",
    "EVENT_PRACTICE_PASSED",
    "EVENT_PRACTICE_SUBMITTED",
    "EVENT_PROJECT_COMPLETED",
    "Execution",
    "HintReveal",
    "ID_LEN",
    "IngestionCandidate",
    "IngestionChunk",
    "IngestionDocument",
    "IngestionRun",
    "IngestionSource",
    "JSONVariant",
    "MasteryEvidence",
    "ProgressEvent",
    "SubjectVersion",
    "Submission",
    "TimestampMixin",
    "User",
    "UserSkillState",
    "UserSubjectEnrollment",
    "UuidType",
    "uuid_pk",
]
