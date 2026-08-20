"""The universal practice model.

One model covers quizzes, code challenges, debugging drills, SQL, terminal work,
architecture design and production incidents. The runtime dispatches on ``kind``
to pick a grader and a UI panel; everything else is shared.

Sanitisation is part of this module and not an afterthought in the API layer.
Answers, solutions and hidden test bodies live on these models, so every model
that holds a secret exposes ``sanitized()`` and the API is only ever allowed to
serialise the result of that call.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .common import Difficulty, Id, MasteryDimension, Provenance, RuntimeKind, SchemaModel, Score, SourceRef


class PracticeKind(str, Enum):
    QUIZ = "quiz"
    CODE = "code"
    DEBUG = "debug"
    SQL = "sql"
    TERMINAL = "terminal"
    API = "api"
    ARCHITECTURE = "architecture"
    INCIDENT = "incident"


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


class Hint(SchemaModel):
    """Progressive disclosure. Level 1 nudges, the last level gives it away.

    Hint usage is recorded and discounts the practice score, which is why the
    ladder must be ordered and why the final level is explicitly marked.
    """

    level: int = Field(ge=1, le=5)
    md: str
    reveals_solution: bool = False


class RubricCriterion(SchemaModel):
    id: Id
    description: str
    weight: float = Field(gt=0.0, le=1.0)
    dimension: MasteryDimension = MasteryDimension.PRACTICE
    automated: bool = Field(
        default=True, description="False means a human or the tutor must judge it; it cannot gate progression."
    )


class Evaluation(SchemaModel):
    strategy: Literal["exact", "pytest", "unit_tests", "sql_result", "state_match", "rubric", "simulation"] = "exact"
    pass_threshold: Score = Field(default=1.0, description="Fraction of weighted checks required to count as passed.")
    rubric: list[RubricCriterion] = Field(default_factory=list)
    partial_credit: bool = True
    dimension: MasteryDimension = Field(
        default=MasteryDimension.PRACTICE,
        description="Which mastery axis a pass on this task provides evidence for.",
    )

    @model_validator(mode="after")
    def _rubric_weights(self) -> "Evaluation":
        if self.rubric:
            total = sum(c.weight for c in self.rubric)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"rubric weights sum to {total}, expected 1.0")
        return self


class SandboxLimits(SchemaModel):
    """Defaults are intentionally mean. Tasks opt into more, never less."""

    runtime: RuntimeKind = RuntimeKind.PYTHON
    runtime_version: str | None = None
    timeout_s: int = Field(default=10, ge=1, le=300)
    memory_mb: int = Field(default=256, ge=64, le=8192)
    cpu_limit: float = Field(default=0.5, gt=0.0, le=4.0)
    pids_limit: int = Field(default=64, ge=8, le=1024)
    network: Literal["none", "egress_allowlist", "full"] = "none"
    egress_allowlist: list[str] = Field(default_factory=list)
    packages: list[str] = Field(
        default_factory=list, description="Must already be present in the runner image; installs are not permitted."
    )

    @model_validator(mode="after")
    def _allowlist_requires_mode(self) -> "SandboxLimits":
        if self.egress_allowlist and self.network != "egress_allowlist":
            raise ValueError("egress_allowlist set but network mode is not 'egress_allowlist'")
        return self


class SourceFile(SchemaModel):
    path: str = Field(description="Relative path inside the workspace. No absolute paths, no '..'.")
    content: str
    readonly: bool = False
    hidden: bool = Field(default=False, description="Present in the sandbox but never shown to the learner.")

    @model_validator(mode="after")
    def _safe_path(self) -> "SourceFile":
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError(f"unsafe file path {self.path!r}")
        return self


class TestCase(SchemaModel):
    id: Id
    name: str = Field(description="Shown to the learner even when the body is hidden, so failures are actionable.")
    kind: Literal["pytest", "unittest", "jest", "io", "sql", "assertion"] = "pytest"
    visible: bool = Field(default=False, description="Whether the learner may read the test body.")
    weight: float = Field(default=1.0, gt=0.0)
    file: str | None = Field(default=None, description="Where the body is written in the sandbox workspace.")
    body: str | None = None
    stdin: str | None = None
    expected_stdout: str | None = None
    timeout_s: int | None = None

    def sanitized(self) -> "TestCase":
        if self.visible:
            return self
        return self.model_copy(update={"body": None, "expected_stdout": None, "stdin": None})


# ---------------------------------------------------------------------------
# Quiz questions
# ---------------------------------------------------------------------------


class QuestionOption(SchemaModel):
    id: str = Field(min_length=1, max_length=8)
    md: str


class BaseQuestion(SchemaModel):
    id: Id
    stem_md: str
    difficulty: Difficulty = 3
    explanation_md: str | None = Field(default=None, description="Revealed after grading, never before.")
    skills: list[Id] = Field(default_factory=list)
    dimension: MasteryDimension = MasteryDimension.CONCEPT
    sources: list[SourceRef] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0.0)


class MCQQuestion(BaseQuestion):
    type: Literal["mcq"] = "mcq"
    options: list[QuestionOption] = Field(min_length=2)
    answer: str

    @model_validator(mode="after")
    def _answer_exists(self) -> "MCQQuestion":
        if self.answer not in {o.id for o in self.options}:
            raise ValueError(f"question {self.id!r} answer {self.answer!r} is not one of its options")
        return self


class MultiSelectQuestion(BaseQuestion):
    type: Literal["multi_select"] = "multi_select"
    options: list[QuestionOption] = Field(min_length=3)
    answer: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _answers_exist(self) -> "MultiSelectQuestion":
        unknown = set(self.answer) - {o.id for o in self.options}
        if unknown:
            raise ValueError(f"question {self.id!r} answers {sorted(unknown)} are not options")
        return self


class FillBlankQuestion(BaseQuestion):
    type: Literal["fill_blank"] = "fill_blank"
    template: str = Field(description="Use {{1}}, {{2}} as blank markers.")
    answer: list[list[str]] = Field(
        description="One entry per blank; each entry is the list of accepted strings for that blank."
    )
    case_sensitive: bool = False


class OrderingQuestion(BaseQuestion):
    type: Literal["ordering"] = "ordering"
    items: list[QuestionOption] = Field(min_length=2)
    answer: list[str] = Field(description="Item ids in correct order.")


class MatchingQuestion(BaseQuestion):
    type: Literal["matching"] = "matching"
    left: list[QuestionOption]
    right: list[QuestionOption]
    answer: dict[str, str] = Field(description="left id -> right id")


class ShortAnswerQuestion(BaseQuestion):
    type: Literal["short_answer"] = "short_answer"
    answer: list[str] = Field(description="Accepted answers, normalised case/whitespace.")
    must_include: list[str] = Field(default_factory=list)


Question = Annotated[
    Union[
        MCQQuestion,
        MultiSelectQuestion,
        FillBlankQuestion,
        OrderingQuestion,
        MatchingQuestion,
        ShortAnswerQuestion,
    ],
    Field(discriminator="type"),
]

_SECRET_QUESTION_FIELDS = ("answer", "explanation_md")


def sanitize_question(question: BaseQuestion) -> dict:
    """Serialise a question with everything that gives away the answer removed."""
    data = question.model_dump(mode="json")
    for field in _SECRET_QUESTION_FIELDS:
        data.pop(field, None)
    data.pop("must_include", None)
    return data


# ---------------------------------------------------------------------------
# Practice tasks
# ---------------------------------------------------------------------------


class PracticeTaskBase(SchemaModel):
    id: Id
    title: str
    subject_id: Id
    concept_id: Id | None = None
    skills: list[Id] = Field(default_factory=list)
    difficulty: Difficulty = 5
    estimated_minutes: int = Field(default=5, ge=1, le=480)
    prompt_md: str = Field(description="What the learner is asked to do.")
    hints: list[Hint] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    evaluation: Evaluation = Field(default_factory=Evaluation)

    @model_validator(mode="after")
    def _hint_ladder_ordered(self) -> "PracticeTaskBase":
        levels = [h.level for h in self.hints]
        if levels != sorted(set(levels)):
            raise ValueError(f"task {self.id!r} hint levels must be unique and ascending, got {levels}")
        return self

    def public_fields(self) -> dict:
        data = self.model_dump(mode="json")
        data["hint_count"] = len(self.hints)
        data.pop("hints", None)
        return data

    def sanitized(self) -> dict:
        return self.public_fields()


class QuizTask(PracticeTaskBase):
    kind: Literal["quiz"] = "quiz"
    questions: list[Question] = Field(min_length=1)
    shuffle: bool = True
    time_limit_s: int | None = None

    def sanitized(self) -> dict:
        data = self.public_fields()
        data["questions"] = [sanitize_question(q) for q in self.questions]
        return data


class CodeTask(PracticeTaskBase):
    kind: Literal["code"] = "code"
    environment: SandboxLimits = Field(default_factory=SandboxLimits)
    starter_files: list[SourceFile] = Field(default_factory=list)
    solution_files: list[SourceFile] = Field(default_factory=list)
    tests: list[TestCase] = Field(default_factory=list)
    entrypoint: str = Field(default="main.py")
    run_command: str | None = Field(default=None, description="Overrides the runner image default.")
    requirements_md: list[str] = Field(
        default_factory=list, description="Checklist shown beside the editor. Complexity bounds belong here."
    )

    def sanitized(self) -> dict:
        data = self.public_fields()
        data.pop("solution_files", None)
        data["starter_files"] = [f.model_dump(mode="json") for f in self.starter_files if not f.hidden]
        data["tests"] = [t.sanitized().model_dump(mode="json") for t in self.tests]
        return data


class DebugTask(CodeTask):
    """A code task that starts from broken code.

    Separate kind because it scores the debugging dimension, and because the UI
    leads with the failing output rather than a blank editor.
    """

    kind: Literal["debug"] = "debug"  # type: ignore[assignment]
    symptom_md: str = Field(description="The failure as the learner first encounters it.")
    broken_files: list[SourceFile] = Field(default_factory=list)
    root_cause_md: str | None = Field(default=None, description="Revealed only after a pass.")

    def sanitized(self) -> dict:
        data = super().sanitized()
        data.pop("root_cause_md", None)
        data["starter_files"] = [f.model_dump(mode="json") for f in self.broken_files if not f.hidden]
        return data


class SQLTask(PracticeTaskBase):
    kind: Literal["sql"] = "sql"
    environment: SandboxLimits = Field(default_factory=lambda: SandboxLimits(runtime=RuntimeKind.SQL))
    schema_sql: str
    seed_sql: str | None = None
    expected_result: list[dict] | None = None
    solution_sql: str | None = None
    ordered: bool = Field(default=False, description="Whether row order is part of correctness.")

    def sanitized(self) -> dict:
        data = self.public_fields()
        data.pop("solution_sql", None)
        data.pop("expected_result", None)
        return data


class TerminalTask(PracticeTaskBase):
    kind: Literal["terminal"] = "terminal"
    environment: SandboxLimits = Field(default_factory=lambda: SandboxLimits(runtime=RuntimeKind.BASH))
    initial_filesystem: list[SourceFile] = Field(default_factory=list)
    goal_checks: list[TestCase] = Field(
        default_factory=list, description="Assertions run against the final sandbox state."
    )
    allowed_commands: list[str] = Field(default_factory=list)

    def sanitized(self) -> dict:
        data = self.public_fields()
        data["goal_checks"] = [c.sanitized().model_dump(mode="json") for c in self.goal_checks]
        return data


class APITask(PracticeTaskBase):
    kind: Literal["api"] = "api"
    base_url: str
    requests_spec_md: str | None = None
    expected_calls: list[dict] | None = None

    def sanitized(self) -> dict:
        data = self.public_fields()
        data.pop("expected_calls", None)
        return data


class ArchitectureNode(SchemaModel):
    id: str
    type: str = Field(description="Component type from the subject's topology vocabulary, e.g. 'alb', 'ec2', 'rds'.")
    label: str | None = None
    config: dict = Field(default_factory=dict)


class ArchitectureTask(PracticeTaskBase):
    kind: Literal["architecture"] = "architecture"
    palette: list[str] = Field(description="Component types the learner may place.")
    initial_nodes: list[ArchitectureNode] = Field(default_factory=list)
    initial_edges: list[list[str]] = Field(default_factory=list)
    constraints_md: list[str] = Field(default_factory=list)
    target_properties: list[str] = Field(
        default_factory=list,
        description="Properties the design must satisfy, e.g. 'multi_az', 'no_public_db'. Checked by the evaluator.",
    )
    solution_nodes: list[ArchitectureNode] = Field(default_factory=list)

    def sanitized(self) -> dict:
        data = self.public_fields()
        data.pop("solution_nodes", None)
        return data


class IncidentSignal(SchemaModel):
    """One thing the learner can go and look at during an incident.

    Modelling telemetry explicitly is what makes production mode a diagnosis
    exercise rather than a multiple-choice question wearing a costume: the
    learner must choose what to inspect, and that choice is graded.
    """

    id: Id
    surface: Literal["metric", "log", "trace", "config", "deployment", "topology", "alert"]
    name: str
    payload: str = Field(description="What the learner sees when they inspect it.")
    is_red_herring: bool = False
    reveals: list[Id] = Field(default_factory=list, description="Signal ids unlocked by inspecting this one.")


class IncidentTask(PracticeTaskBase):
    kind: Literal["incident"] = "incident"
    scenario_md: str
    architecture_md: str | None = None
    symptoms: list[str] = Field(min_length=1)
    signals: list[IncidentSignal] = Field(default_factory=list)
    remediations: list[QuestionOption] = Field(
        default_factory=list, description="Candidate actions the learner may take."
    )
    correct_remediations: list[str] = Field(default_factory=list)
    root_cause_md: str | None = None
    max_inspections: int | None = Field(
        default=None, description="Budget on how much telemetry may be pulled. Teaches prioritised diagnosis."
    )

    def sanitized(self) -> dict:
        data = self.public_fields()
        data.pop("correct_remediations", None)
        data.pop("root_cause_md", None)
        data["signals"] = [
            {k: v for k, v in s.model_dump(mode="json").items() if k not in ("payload", "is_red_herring", "reveals")}
            for s in self.signals
        ]
        return data


PracticeTask = Annotated[
    Union[
        QuizTask,
        DebugTask,
        CodeTask,
        SQLTask,
        TerminalTask,
        APITask,
        ArchitectureTask,
        IncidentTask,
    ],
    Field(discriminator="kind"),
]
