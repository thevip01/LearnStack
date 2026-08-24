"""Practice envelopes: task summaries, attempts, hints, submissions.

``PracticeTaskOut`` is deliberately absent. The contract says a practice task
reaches the client only as the output of the schema model's ``sanitized()``, which
returns a plain dict; declaring a response model here would mean re-deriving that
dict's shape and would give a future edit somewhere to accidentally reintroduce
an ``answer`` field. The route returns the dict.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from learnos_schema import ArchitectureNode, ExecutionResult, MasteryDimension
from pydantic import BaseModel, Field, field_validator

from .common import ApiModel, UtcDatetime

PracticeState = Literal["untouched", "in_progress", "passed", "failed"]
SkillState = Literal["untouched", "partially_measured", "developing", "mastered", "at_risk"]


class PracticeSummary(ApiModel):
    id: str
    kind: str
    title: str
    difficulty: int
    estimated_minutes: int
    hint_count: int
    skills: list[str] = Field(default_factory=list)
    state: PracticeState = "untouched"
    best_score: float | None = None
    attempts: int = 0


class PracticeQueueOut(ApiModel):
    tasks: list[PracticeSummary] = Field(default_factory=list)


class AttemptOut(ApiModel):
    attempt_id: str
    task_id: str
    started_at: UtcDatetime
    hints_used: int
    submission_count: int
    time_limit_s: int | None = None


class HintOut(ApiModel):
    level: int
    md: str
    hints_remaining: int
    reveals_solution: bool


# ---------------------------------------------------------------------------
# Submission input
# ---------------------------------------------------------------------------


class SubmittedFile(BaseModel):
    """A file the learner is asking us to write into a sandbox workspace.

    The path check is a security control, not a nicety: this value is attacker
    controlled and is used to build a path inside the workspace tar. Rejecting
    absolute paths and ``..`` segments here means the tar builder never has to.
    """

    path: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=512_000)

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        cleaned = value.strip().replace("\\", "/")
        if cleaned.startswith("/") or cleaned.startswith("~"):
            raise ValueError("file path must be relative to the workspace")
        parts = cleaned.split("/")
        if any(part in ("..", "") for part in parts):
            raise ValueError("file path may not contain '..' or empty segments")
        if any(ch in cleaned for ch in ("\x00", "\n", "\r")):
            raise ValueError("file path contains control characters")
        return cleaned


class QuizSubmitIn(BaseModel):
    kind: Literal["quiz"]
    #: question id -> answer. A string for mcq/short_answer, a list for
    #: multi_select/ordering/fill_blank, a mapping for matching.
    answers: dict[str, Union[str, list[str], dict[str, str]]] = Field(default_factory=dict)


class CodeSubmitIn(BaseModel):
    kind: Literal["code"]
    files: list[SubmittedFile] = Field(min_length=1, max_length=64)


class DebugSubmitIn(BaseModel):
    """Same payload as ``code``; a separate arm because the discriminator differs."""

    kind: Literal["debug"]
    files: list[SubmittedFile] = Field(min_length=1, max_length=64)


class SQLSubmitIn(BaseModel):
    kind: Literal["sql"]
    sql: str = Field(min_length=1, max_length=100_000)


class TerminalSubmitIn(BaseModel):
    kind: Literal["terminal"]
    commands: list[str] = Field(min_length=1, max_length=100)


class ArchitectureSubmitIn(BaseModel):
    kind: Literal["architecture"]
    nodes: list[ArchitectureNode] = Field(default_factory=list, max_length=200)
    #: ``[source_id, target_id]`` pairs.
    edges: list[list[str]] = Field(default_factory=list, max_length=500)

    @field_validator("edges")
    @classmethod
    def _pairs(cls, value: list[list[str]]) -> list[list[str]]:
        for edge in value:
            if len(edge) != 2:
                raise ValueError("each edge must be a [source, target] pair")
        return value


class IncidentSubmitIn(BaseModel):
    kind: Literal["incident"]
    inspected: list[str] = Field(default_factory=list, max_length=200)
    remediations: list[str] = Field(default_factory=list, max_length=50)
    root_cause: str | None = Field(default=None, max_length=4_000)


SubmitIn = Annotated[
    Union[
        QuizSubmitIn,
        CodeSubmitIn,
        DebugSubmitIn,
        SQLSubmitIn,
        TerminalSubmitIn,
        ArchitectureSubmitIn,
        IncidentSubmitIn,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Submission output
# ---------------------------------------------------------------------------


class QuestionResultOut(ApiModel):
    question_id: str
    correct: bool
    #: ``null`` on a wrong answer to a non-final attempt of a graded assessment:
    #: revealing it there would turn a retake into a memory test.
    expected: Any | None = None
    explanation_md: str | None = None


class MasteryDeltaOut(ApiModel):
    skill_id: str
    title: str
    dimension: MasteryDimension
    before: float
    after: float
    state: SkillState


class RevealOut(ApiModel):
    solution_files: list[SubmittedFile] | None = None
    root_cause_md: str | None = None
    correct_remediations: list[str] | None = None


class NextUpOut(ApiModel):
    kind: str
    id: str
    title: str
    #: Composed by the recommender. The frontend renders it verbatim.
    reason: str


class SubmissionResultOut(ApiModel):
    attempt_id: str
    task_id: str
    passed: bool
    score: float
    dimension: MasteryDimension
    hints_used: int
    duration_ms: int
    feedback_md: str
    execution: ExecutionResult | None = None
    question_results: list[QuestionResultOut] | None = None
    mastery_deltas: list[MasteryDeltaOut] = Field(default_factory=list)
    unlocked_skills: list[str] = Field(default_factory=list)
    reveal: RevealOut | None = None
    next: NextUpOut | None = None
