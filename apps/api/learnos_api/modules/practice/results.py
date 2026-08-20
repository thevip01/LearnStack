"""What a grader returns.

Every grader — quiz, code, sql, terminal, architecture, incident — produces this
one shape, and the submission pipeline never branches on task kind again after
the grader returns. That is the whole reason this dataclass exists: without it,
"what does a pass mean" would be answered slightly differently in seven places.

Two rules that every grader in this package has to hold to:

* **A learner's code failing is not an error.** Failing tests, a syntax error, a
  timeout and a memory blow-up all produce a ``GradeOutcome`` with a low score.
  An exception out of a grader means the *platform* broke.
* **Feedback is composed here, server-side.** The contract forbids the frontend
  from composing feedback text, so a grader that returns an empty
  ``feedback_md`` has produced a screen with nothing on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from learnos_schema import Evaluation, ExecutionResult

from ...schemas.practice import QuestionResultOut


@dataclass
class GradeOutcome:
    """The graded result of one submission against one task."""

    score: float
    passed: bool
    feedback_md: str
    #: Populated by the quiz grader only. ``None`` means "not a question task",
    #: which is different from "a question task with no results".
    question_results: list[QuestionResultOut] | None = None
    #: The sandbox run behind this grade, when there was one. Serialised to the
    #: client, so anything secret must already have been redacted.
    execution: ExecutionResult | None = None
    #: Grader-internal notes. Logged, never serialised.
    notes: list[str] = field(default_factory=list)

    def clamped(self) -> "GradeOutcome":
        self.score = min(max(float(self.score), 0.0), 1.0)
        return self


def weighted_fraction(pairs: list[tuple[bool, float]]) -> float:
    """Fraction of total weight that passed.

    An empty check set scores 0 rather than 1. A task with no tests is a content
    bug, and scoring it as a pass would let that bug hand out mastery.
    """
    total = sum(weight for _, weight in pairs)
    if total <= 0:
        return 0.0
    earned = sum(weight for ok, weight in pairs if ok)
    return earned / total


def decide(fraction: float, evaluation: Evaluation) -> tuple[float, bool]:
    """Apply the task's evaluation policy to a raw weighted fraction.

    ``partial_credit=False`` means the score is all-or-nothing: a learner who got
    four of five hidden tests green on a task marked as indivisible has not half
    solved it, and recording 0.8 would feed mastery evidence for work that does
    not run.
    """
    passed = fraction >= float(evaluation.pass_threshold)
    if not evaluation.partial_credit:
        return (1.0 if passed else 0.0), passed
    return min(max(fraction, 0.0), 1.0), passed
