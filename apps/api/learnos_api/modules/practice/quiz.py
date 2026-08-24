"""Quiz grading.

Pure functions: questions and answers in, scores out. No database, no sandbox, no
clock. That makes every rule in here directly testable, which matters because
this is the code that decides whether a learner got a question wrong, and a
grader that is wrong in a subtle way is worse than one that is broken loudly.

The comparison rules are deliberately forgiving about *presentation* and strict
about *content*:

* Whitespace and case are normalised for text answers, because "Reference" and
  "reference " are the same answer and marking one wrong teaches nothing.
* Order matters only where the question says it does: ``ordering`` cares,
  ``multi_select`` does not.
* ``short_answer`` accepts any of the authored alternatives, and additionally
  requires every ``must_include`` fragment. That is how an authored question asks
  for "mentions both the name and the object" without a rubric.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from learnos_schema import QuizTask

from ...schemas.practice import QuestionResultOut
from ..subjects.assemble import enum_value
from .results import GradeOutcome, decide, weighted_fraction

_WHITESPACE = re.compile(r"\s+")


def normalise_text(value: Any, *, case_sensitive: bool = False) -> str:
    """Collapse whitespace, strip, and fold case unless the question forbids it.

    Also strips a trailing period and surrounding quotes: a learner who types
    ``"reference".`` has answered the question.
    """
    text = _WHITESPACE.sub(" ", str(value)).strip().strip("\"'").rstrip(".")
    return text if case_sensitive else text.casefold()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, Mapping):
        return [str(item) for item in value.values()]
    return [str(value)]


def _question_field(question: Any, name: str, default: Any = None) -> Any:
    """Read a field off a question model or its dict form.

    Questions arrive as validated models everywhere in this service, but the quiz
    grader is also the natural place to replay a historical submission from the
    ``submissions.payload`` column, where they are dicts.
    """
    if isinstance(question, Mapping):
        return question.get(name, default)
    return getattr(question, name, default)


# ---------------------------------------------------------------------------
# Per-type comparison
# ---------------------------------------------------------------------------


def grade_mcq(question: Any, submitted: Any) -> bool:
    return normalise_text(submitted, case_sensitive=True) == normalise_text(
        _question_field(question, "answer"), case_sensitive=True
    )


def grade_multi_select(question: Any, submitted: Any) -> bool:
    """Exact set match. No partial credit within a single question.

    Partial credit per option would reward "select everything", which is the
    failure mode multi-select exists to detect.
    """
    expected = {normalise_text(item, case_sensitive=True) for item in _as_list(_question_field(question, "answer"))}
    given = {normalise_text(item, case_sensitive=True) for item in _as_list(submitted)}
    return expected == given


def grade_ordering(question: Any, submitted: Any) -> bool:
    expected = [normalise_text(item, case_sensitive=True) for item in _as_list(_question_field(question, "answer"))]
    given = [normalise_text(item, case_sensitive=True) for item in _as_list(submitted)]
    return expected == given


def grade_matching(question: Any, submitted: Any) -> bool:
    expected = _question_field(question, "answer") or {}
    if not isinstance(submitted, Mapping):
        return False
    if set(expected) != set(submitted):
        return False
    return all(
        normalise_text(submitted.get(left), case_sensitive=True) == normalise_text(right, case_sensitive=True)
        for left, right in expected.items()
    )


def grade_fill_blank(question: Any, submitted: Any) -> bool:
    """Every blank must match one of its accepted alternatives.

    ``answer`` is a list per blank, so blank *n* is graded against
    ``answer[n]``. A submission with the wrong number of blanks is wrong rather
    than an error: the client can send a short list if the learner left one empty.
    """
    accepted: Iterable[Iterable[str]] = _question_field(question, "answer") or []
    accepted_list = [list(group) for group in accepted]
    case_sensitive = bool(_question_field(question, "case_sensitive", False))
    given = _as_list(submitted)
    if len(given) != len(accepted_list):
        return False
    for value, alternatives in zip(given, accepted_list):
        normalised = normalise_text(value, case_sensitive=case_sensitive)
        if not any(normalised == normalise_text(alt, case_sensitive=case_sensitive) for alt in alternatives):
            return False
    return True


def grade_short_answer(question: Any, submitted: Any) -> bool:
    text = normalise_text(submitted)
    if not text:
        return False
    accepted = [normalise_text(item) for item in _as_list(_question_field(question, "answer"))]
    must_include = [normalise_text(item) for item in _as_list(_question_field(question, "must_include", []))]

    if must_include and not all(fragment in text for fragment in must_include):
        return False
    if accepted and any(text == candidate for candidate in accepted):
        return True
    # Containment fallback: an authored answer of "late binding" should accept
    # "it is late binding of the closure variable". Only applied when the
    # authored answer is a phrase rather than a single short token, so "no" does
    # not match "not at all".
    if any(len(candidate) >= 4 and candidate in text for candidate in accepted):
        return True
    # A question with must_include and no answer alternatives is graded purely on
    # the required fragments, which the check above has already satisfied.
    return bool(must_include) and not accepted


_GRADERS = {
    "mcq": grade_mcq,
    "multi_select": grade_multi_select,
    "ordering": grade_ordering,
    "matching": grade_matching,
    "fill_blank": grade_fill_blank,
    "short_answer": grade_short_answer,
}


def grade_question(question: Any, submitted: Any) -> bool:
    grader = _GRADERS.get(enum_value(_question_field(question, "type")))
    if grader is None:
        # An unknown type is a content bug, not a learner failure. Marking it
        # correct would hand out unearned mastery; marking it wrong would punish
        # the learner for it. Wrong-but-logged is the lesser evil and the package
        # validator is what should have caught it.
        return False
    return grader(question, submitted)


# ---------------------------------------------------------------------------
# Whole-task grading
# ---------------------------------------------------------------------------


def expected_for_display(question: Any) -> Any:
    """The answer, in the shape the UI shows after grading."""
    answer = _question_field(question, "answer")
    if isinstance(answer, list) and answer and isinstance(answer[0], list):
        # fill_blank: show the first accepted alternative for each blank rather
        # than the full alternatives matrix, which is noise to a learner.
        return [group[0] if group else "" for group in answer]
    return answer


def grade_quiz(
    task: QuizTask,
    answers: Mapping[str, Any],
    *,
    reveal_expected: bool = True,
) -> GradeOutcome:
    """Grade a whole quiz submission.

    ``reveal_expected=False`` is the graded-assessment path: the learner is told
    which questions were wrong but not what the answer was, because a retake has
    to be a second attempt at the reasoning rather than a memory test.
    """
    results: list[QuestionResultOut] = []
    weighted: list[tuple[bool, float]] = []

    for question in task.questions:
        question_id = str(_question_field(question, "id"))
        submitted = answers.get(question_id)
        correct = submitted is not None and grade_question(question, submitted)
        weight = float(_question_field(question, "weight", 1.0) or 1.0)
        weighted.append((correct, weight))
        results.append(
            QuestionResultOut(
                question_id=question_id,
                correct=correct,
                expected=None if (not correct and not reveal_expected) else expected_for_display(question),
                explanation_md=_question_field(question, "explanation_md"),
            )
        )

    fraction = weighted_fraction(weighted)
    score, passed = decide(fraction, task.evaluation)
    correct_count = sum(1 for result in results if result.correct)

    return GradeOutcome(
        score=score,
        passed=passed,
        feedback_md=_quiz_feedback(correct_count, len(results), passed, task),
        question_results=results,
    ).clamped()


def _quiz_feedback(correct: int, total: int, passed: bool, task: QuizTask) -> str:
    threshold = int(round(float(task.evaluation.pass_threshold) * 100))
    if total == 0:
        return "This quiz has no questions. That is a content bug. Please report it."
    headline = f"**{correct} of {total} correct.**"
    if passed:
        return f"{headline} That clears the {threshold}% needed to pass."
    missed = total - correct
    noun = "question" if missed == 1 else "questions"
    return (
        f"{headline} You need {threshold}% to pass, so review the {missed} {noun} "
        "marked below and try again: the explanations say what the expected "
        "reasoning was."
    )
