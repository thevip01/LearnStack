"""Code and debug grading.

This is the module that turns "the learner pressed Run" into a number, and it is
where three separate concerns meet: assembling a workspace, driving the sandbox,
and deciding what the learner is allowed to see about why they failed.

The rules that must not be relaxed:

* **A learner's files never overwrite authored material.** Test bodies, readonly
  starter files, the harness and its manifest are all applied after the
  submission and win every collision. Without that, "solve the task" reduces to
  "replace the test file with ``def test_x(): pass``".
* **Hidden test output is redacted here, once.** The harness reports assertion
  text for every test because it does not know which are visible; this grader is
  the only place that does. A hidden test's failure message is replaced with its
  authored ``name``, which is why the schema requires a name even when the body
  is secret.
* **A failing submission is a successful execution.** Only a broken platform
  raises.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from learnos_schema import (
    CodeTask,
    DebugTask,
    ExecutionRequest,
    ExecutionResult,
    SourceFile,
    TestCase,
    TestResult,
)
from learnos_sandbox import HARNESS_FILENAME, MANIFEST_FILENAME, TestSpec

from ...logging import get_logger
from ..execution.service import ExecutionService, status_value
from .results import GradeOutcome, decide, weighted_fraction

log = get_logger(__name__)

#: Shown in place of a hidden test's assertion output.
HIDDEN_MESSAGE = "This check is hidden. Its name says what it verifies."

#: Where a test body goes when the author did not say.
DEFAULT_TEST_DIR = "tests"

_TEST_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_[A-Za-z0-9_]*)", re.MULTILINE)


def test_file_path(test: TestCase) -> str:
    """Where a test body is written in the workspace."""
    if test.file:
        return test.file
    safe = re.sub(r"[^a-z0-9_]+", "_", test.id.lower()).strip("_") or "case"
    return f"{DEFAULT_TEST_DIR}/test_{safe}.py"


def test_functions(test: TestCase) -> list[str]:
    """Function names in a test body, so the harness can map node ids to ids.

    Derived here because this is the only layer that holds the body — the
    manifest deliberately does not carry it.
    """
    if not test.body:
        return []
    return _TEST_FUNCTION_RE.findall(test.body)


def test_specs(tests: Sequence[TestCase]) -> list[TestSpec]:
    return [
        TestSpec(
            id=test.id,
            name=test.name,
            weight=float(test.weight),
            file=test_file_path(test),
            functions=test_functions(test),
        )
        for test in tests
        if test.body
    ]


# ---------------------------------------------------------------------------
# Workspace assembly
# ---------------------------------------------------------------------------


def authored_baseline(task: CodeTask) -> list[SourceFile]:
    """The files the learner starts from.

    A debug task hands over ``broken_files`` — the point of the exercise is that
    the starting state is wrong — and falls back to ``starter_files`` if an author
    left the list empty.
    """
    if isinstance(task, DebugTask) and task.broken_files:
        return list(task.broken_files)
    return list(task.starter_files)


def protected_paths(task: CodeTask) -> set[str]:
    """Paths a submission may not write to.

    Three groups: the harness and its manifest, every test body's file, and every
    starter file the author marked readonly. All three are answer-bearing or
    integrity-bearing, and all three are attacker-controlled targets in the sense
    that the learner chooses the paths in their submission.
    """
    protected = {HARNESS_FILENAME, MANIFEST_FILENAME}
    protected.update(test_file_path(test) for test in task.tests if test.body)
    protected.update(source.path for source in authored_baseline(task) if source.readonly)
    protected.update(source.path for source in task.starter_files if source.readonly or source.hidden)
    return protected


def build_workspace(
    task: CodeTask,
    submitted: Iterable[Mapping[str, str]],
) -> tuple[list[SourceFile], list[str]]:
    """Merge authored files with the submission.

    Returns ``(files, rejected_paths)``. A rejected path is reported back to the
    learner rather than silently dropped: "your edit to ``tests/test_x.py`` was
    ignored" is useful feedback, and pretending the write happened would make the
    result inexplicable.
    """
    blocked = protected_paths(task)
    files: dict[str, SourceFile] = {}

    for source in authored_baseline(task):
        files[source.path] = source

    rejected: list[str] = []
    for item in submitted:
        path = str(item["path"] if isinstance(item, Mapping) else item.path)  # type: ignore[union-attr]
        content = str(item["content"] if isinstance(item, Mapping) else item.content)  # type: ignore[union-attr]
        if path in blocked:
            rejected.append(path)
            continue
        files[path] = SourceFile(path=path, content=content)

    # Test bodies last: they overwrite anything with the same path, including a
    # file the learner slipped past the blocklist by a path-normalisation quirk.
    for test in task.tests:
        if test.body:
            files[test_file_path(test)] = SourceFile(path=test_file_path(test), content=test.body, hidden=True)

    return list(files.values()), rejected


def execution_request(task: CodeTask, files: list[SourceFile]) -> ExecutionRequest:
    return ExecutionRequest(
        files=files,
        limits=task.environment,
        command=task.run_command,
        collect_artifacts=[],
    )


# ---------------------------------------------------------------------------
# Result interpretation
# ---------------------------------------------------------------------------


def visible_ids(task: CodeTask) -> set[str]:
    return {test.id for test in task.tests if test.visible}


def test_results_from_report(task: CodeTask, report: Mapping[str, object] | None) -> list[TestResult]:
    """Harness report -> ``TestResult`` list, with hidden output redacted.

    The redaction happens on the way *in* to the result object, not on the way
    out to HTTP. That ordering matters: the result is serialised by the response
    model without further inspection, so anything that reaches it is public.
    """
    if not report:
        return []
    visible = visible_ids(task)
    weights = {test.id: float(test.weight) for test in task.tests}
    out: list[TestResult] = []
    for entry in report.get("tests", []) or []:  # type: ignore[union-attr]
        if not isinstance(entry, Mapping):
            continue
        test_id = str(entry.get("test_id") or "")
        is_visible = test_id in visible
        passed = bool(entry.get("passed"))
        message = entry.get("message")
        if not passed and not is_visible:
            message = HIDDEN_MESSAGE
        out.append(
            TestResult(
                test_id=test_id or "unknown",
                name=str(entry.get("name") or test_id),
                passed=passed,
                weight=weights.get(test_id, float(entry.get("weight", 1.0) or 1.0)),
                duration_ms=int(entry.get("duration_ms") or 0),
                message=str(message) if message else None,
                # Tracebacks are never forwarded. A visible test's assertion text
                # is in ``message``; a hidden test's traceback quotes its own
                # source, which is the thing being protected.
                traceback=None,
            )
        )
    return out


def redact_execution(task: CodeTask, result: ExecutionResult) -> ExecutionResult:
    """Strip references to hidden files out of raw output.

    The harness already captures everything pytest writes, so this is a second
    line of defence for the narrow window where a learner's own code prints or
    raises inside a hidden test's import. It removes whole lines that name a
    hidden path rather than trying to be clever: a partially scrubbed traceback
    is worse than a missing line.
    """
    hidden = {test_file_path(test) for test in task.tests if test.body and not test.visible}
    hidden.update(source.path for source in task.starter_files if source.hidden)
    hidden.update(source.path for source in task.solution_files)
    if not hidden:
        return result

    def scrub(text: str) -> str:
        if not text:
            return text
        kept = [line for line in text.splitlines() if not any(path in line for path in hidden)]
        return "\n".join(kept)

    return result.model_copy(update={"stdout": scrub(result.stdout), "stderr": scrub(result.stderr)})


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


async def grade_code(
    task: CodeTask,
    submitted_files: Iterable[Mapping[str, str]],
    *,
    execution: ExecutionService,
    execution_id: str | None = None,
) -> GradeOutcome:
    """Run the submission against the task's tests and score it."""
    files, rejected = build_workspace(task, submitted_files)
    specs = test_specs(task.tests)

    if not specs:
        # No runnable tests. The package validator warns about this; grading it as
        # a pass would mint mastery from an empty check set.
        return GradeOutcome(
            score=0.0,
            passed=False,
            feedback_md=(
                "This task has no runnable tests, so there is nothing to grade. "
                "That is a content bug — please report it."
            ),
            notes=["task has no test bodies"],
        )

    outcome = await execution.run_tests(
        execution_request(task, files),
        specs=specs,
        execution_id=execution_id,
    )
    result = redact_execution(task, outcome.result)
    tests = test_results_from_report(task, outcome.report)
    result = result.model_copy(update={"tests": tests})

    status = status_value(result)
    if not tests:
        return GradeOutcome(
            score=0.0,
            passed=False,
            feedback_md=_no_report_feedback(status, result),
            execution=result,
            notes=[f"no harness report; status={status}"],
        ).clamped()

    fraction = weighted_fraction([(test.passed, test.weight) for test in tests])
    score, passed = decide(fraction, task.evaluation)
    return GradeOutcome(
        score=score,
        passed=passed,
        feedback_md=_code_feedback(task, tests, passed, rejected, status),
        execution=result,
    ).clamped()


async def grade_debug(
    task: DebugTask,
    submitted_files: Iterable[Mapping[str, str]],
    *,
    execution: ExecutionService,
    execution_id: str | None = None,
) -> GradeOutcome:
    """Identical mechanics to ``grade_code``; only the framing differs.

    A debug task is a code task whose starting files are wrong, so the grading
    path is shared on purpose. Forking it would be two implementations of the
    redaction rules.
    """
    return await grade_code(task, submitted_files, execution=execution, execution_id=execution_id)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def _no_report_feedback(status: str, result: ExecutionResult) -> str:
    if status == "timeout":
        return (
            "**Timed out.** Your code was still running when the time limit hit. "
            "That usually means a loop that never ends or a call that waits on "
            "something the sandbox has no network access to reach."
        )
    if status == "memory_exceeded":
        return (
            "**Ran out of memory.** Something is holding on to more data than the "
            "sandbox allows — often a list that grows inside a loop."
        )
    detail = (result.stderr or result.stdout or "").strip()
    tail = "\n\n```\n" + detail[-1200:] + "\n```" if detail else ""
    return (
        "**The test run did not complete.** Nothing was scored because the test "
        "suite could not be collected — usually a syntax error or an import that "
        "fails before any test runs." + tail
    )


def _code_feedback(
    task: CodeTask,
    tests: list[TestResult],
    passed: bool,
    rejected: list[str],
    status: str,
) -> str:
    total_weight = sum(test.weight for test in tests) or 1.0
    earned = sum(test.weight for test in tests if test.passed)
    failing = [test for test in tests if not test.passed]

    lines: list[str] = []
    if passed:
        lines.append(f"**Passed.** {len(tests) - len(failing)} of {len(tests)} checks green.")
    else:
        lines.append(
            f"**Not yet.** {len(tests) - len(failing)} of {len(tests)} checks green "
            f"({earned / total_weight:.0%} by weight); "
            f"{int(round(float(task.evaluation.pass_threshold) * 100))}% is needed."
        )

    if failing:
        lines.append("")
        lines.append("Failing checks:")
        for test in failing[:8]:
            note = f" — {test.message.splitlines()[0][:200]}" if test.message else ""
            lines.append(f"- `{test.name}`{note}")
        if len(failing) > 8:
            lines.append(f"- …and {len(failing) - 8} more")

    if isinstance(task, DebugTask) and not passed:
        lines.append("")
        lines.append("Re-read the symptom above and check your assumption about *why* it fails before changing more code.")

    if rejected:
        lines.append("")
        lines.append(
            "Ignored edits to protected files: " + ", ".join(f"`{path}`" for path in sorted(set(rejected))) + "."
        )

    if status == "timeout":
        lines.append("")
        lines.append("The run also hit the time limit, so later checks may not have run at all.")

    return "\n".join(lines)
