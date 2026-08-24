"""Terminal grading.

A terminal task gives the learner a filesystem and a goal, they submit a sequence
of commands, and the grader checks the *end state*, not the commands. That
distinction is the whole design: there are five reasonable ways to move a file,
and a grader that pattern-matches the command string teaches the learner to guess
the author's phrasing rather than to use the tool.

Like the SQL grader, this runs inside the Python sandbox: a generated driver
executes each command with ``bash -lc``, then runs the authored goal checks. Two
consequences worth stating plainly:

* The runner image ships bash and coreutils but is not a general Linux box. A task
  that needs ``systemctl`` or a package manager needs its own runtime image.
* Commands run with the sandbox's network disabled and the same rlimits as any
  other submission, so ``curl`` failing is expected, not a bug.

A goal check is a ``TestCase``: ``body`` is a shell snippet whose exit status
decides the check, or ``expected_stdout`` is compared against the combined output
of the learner's commands.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from learnos_schema import ExecutionRequest, SandboxLimits, SourceFile, TerminalTask, TestCase, TestResult

from ..execution.service import ExecutionService, status_value
from .results import GradeOutcome, decide, weighted_fraction

DRIVER_FILENAME = "_learnos_shell_driver.py"
PLAN_FILENAME = "_learnos_shell_plan.json"
SENTINEL = "__LEARNOS_SHELL_V1__"

HIDDEN_MESSAGE = "This check is hidden. Its name says what it verifies."

_DRIVER = '''
import json, subprocess, sys

SENTINEL = "{sentinel}"
PER_COMMAND_TIMEOUT = 20


def run(script):
    try:
        completed = subprocess.run(
            ["bash", "-lc", script],
            capture_output=True,
            text=True,
            timeout=PER_COMMAND_TIMEOUT,
        )
        return completed.returncode, completed.stdout[-4000:], completed.stderr[-2000:]
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out"
    except Exception as exc:
        return 125, "", str(exc)


def main():
    with open("{plan_file}", "r", encoding="utf-8") as handle:
        plan = json.load(handle)

    transcript = []
    combined = []
    for command in plan.get("commands") or []:
        code, out, err = run(command)
        transcript.append({{"command": command, "exit_code": code, "stdout": out, "stderr": err}})
        combined.append(out)
        # Keep going after a failure: a later command may be the one that matters,
        # and stopping would hide the rest of the learner's reasoning.

    checks = []
    for check in plan.get("checks") or []:
        body = check.get("body")
        expected = check.get("expected_stdout")
        if body:
            code, out, err = run(body)
            checks.append({{
                "id": check.get("id"),
                "passed": code == 0,
                "detail": (err or out or "").strip()[-500:],
            }})
        elif expected is not None:
            actual = "".join(combined)
            checks.append({{
                "id": check.get("id"),
                "passed": expected.strip() in actual.strip(),
                "detail": "expected output not found" if expected.strip() not in actual.strip() else "",
            }})
        else:
            checks.append({{"id": check.get("id"), "passed": False, "detail": "check has nothing to verify"}})

    sys.stdout.write(
        "\\n" + SENTINEL + " " + json.dumps({{"transcript": transcript, "checks": checks}}, default=str) + "\\n"
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _driver_source() -> str:
    return _DRIVER.format(sentinel=SENTINEL, plan_file=PLAN_FILENAME)


def _plan(task: TerminalTask, commands: Sequence[str]) -> str:
    return json.dumps(
        {
            "commands": list(commands),
            "checks": [
                {"id": check.id, "body": check.body, "expected_stdout": check.expected_stdout}
                for check in task.goal_checks
            ],
        },
        indent=2,
    )


def _parse(stdout: str) -> dict[str, Any] | None:
    payload: dict[str, Any] | None = None
    for line in stdout.splitlines():
        if line.startswith(SENTINEL):
            try:
                candidate = json.loads(line[len(SENTINEL) :].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
    return payload


def _disallowed(task: TerminalTask, commands: Sequence[str]) -> list[str]:
    """Commands the task's allowlist forbids.

    This is a teaching constraint, not a security control: the sandbox is what
    provides safety. A task that says "do this with ``find``" is entitled to
    reject ``python -c``, and the rejection has to be explained rather than
    silently scored as a fail.
    """
    if not task.allowed_commands:
        return []
    allowed = {name.strip() for name in task.allowed_commands if name.strip()}
    bad: list[str] = []
    for command in commands:
        for segment in command.replace("&&", ";").replace("||", ";").replace("|", ";").split(";"):
            head = segment.strip().split(" ")[0]
            if head and head not in allowed:
                bad.append(head)
    return sorted(set(bad))


async def grade_terminal(
    task: TerminalTask,
    commands: Sequence[str],
    *,
    execution: ExecutionService,
    execution_id: str | None = None,
) -> GradeOutcome:
    blocked = _disallowed(task, commands)
    if blocked:
        return GradeOutcome(
            score=0.0,
            passed=False,
            feedback_md=(
                "**Not scored.** This task limits you to "
                + ", ".join(f"`{name}`" for name in sorted(task.allowed_commands))
                + ", and your commands used "
                + ", ".join(f"`{name}`" for name in blocked)
                + "."
            ),
            notes=[f"disallowed commands: {blocked}"],
        )

    if not task.goal_checks:
        return GradeOutcome(
            score=0.0,
            passed=False,
            feedback_md="This task has no goal checks, so there is nothing to verify. Please report it.",
            notes=["task has no goal_checks"],
        )

    files: list[SourceFile] = list(task.initial_filesystem)
    files.append(SourceFile(path=PLAN_FILENAME, content=_plan(task, commands), readonly=True, hidden=True))
    files.append(SourceFile(path=DRIVER_FILENAME, content=_driver_source(), readonly=True, hidden=True))

    limits = task.environment.model_copy(update={"runtime": "python", "runtime_version": None})
    if not isinstance(limits, SandboxLimits):  # pragma: no cover - defensive
        limits = SandboxLimits()

    outcome = await execution.execute(
        ExecutionRequest(files=files, limits=limits, command=f"python -I {DRIVER_FILENAME}"),
        execution_id=execution_id,
    )
    result = outcome.result
    payload = _parse(result.stdout)
    cleaned = "\n".join(line for line in result.stdout.splitlines() if not line.startswith(SENTINEL))
    result = result.model_copy(update={"stdout": cleaned})

    if payload is None:
        status = status_value(result)
        message = (
            "**Timed out.** The commands were still running at the time limit."
            if status == "timeout"
            else "**The commands could not be run.** Nothing was scored."
        )
        return GradeOutcome(score=0.0, passed=False, feedback_md=message, execution=result).clamped()

    by_id = {str(entry.get("id")): entry for entry in payload.get("checks") or [] if isinstance(entry, dict)}
    tests: list[TestResult] = []
    for check in task.goal_checks:
        entry = by_id.get(check.id, {})
        ok = bool(entry.get("passed"))
        detail = str(entry.get("detail") or "")
        tests.append(
            TestResult(
                test_id=check.id,
                name=check.name,
                passed=ok,
                weight=float(check.weight),
                message=None if ok else (detail if check.visible and detail else HIDDEN_MESSAGE),
            )
        )

    result = result.model_copy(update={"tests": tests})
    fraction = weighted_fraction([(test.passed, test.weight) for test in tests])
    score, passed = decide(fraction, task.evaluation)

    transcript = payload.get("transcript") or []
    failed_commands = [
        entry for entry in transcript if isinstance(entry, dict) and int(entry.get("exit_code") or 0) != 0
    ]
    return GradeOutcome(
        score=score,
        passed=passed,
        feedback_md=_terminal_feedback(tests, passed, failed_commands),
        execution=result,
    ).clamped()


def _terminal_feedback(tests: list[TestResult], passed: bool, failed_commands: list[dict[str, Any]]) -> str:
    green = sum(1 for test in tests if test.passed)
    lines = [
        f"**Passed.** {green} of {len(tests)} goal checks met."
        if passed
        else f"**Not yet.** {green} of {len(tests)} goal checks met."
    ]
    failing = [test for test in tests if not test.passed]
    if failing:
        lines.append("")
        lines.append("Unmet goals:")
        for test in failing[:8]:
            note = f": {test.message.splitlines()[0][:200]}" if test.message else ""
            lines.append(f"- `{test.name}`{note}")
    if failed_commands:
        lines.append("")
        lines.append("Commands that exited non-zero:")
        for entry in failed_commands[:5]:
            stderr = str(entry.get("stderr") or "").splitlines()
            first = stderr[0][:160] if stderr else ""
            lines.append(f"- `{entry.get('command')}` (exit {entry.get('exit_code')}){': ' + first if first else ''}")
    return "\n".join(lines)


def visible_checks(task: TerminalTask) -> list[TestCase]:
    return [check for check in task.goal_checks if check.visible]
