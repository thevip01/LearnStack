"""SQL grading.

There is no SQL runner image. Rather than ship a second sandbox, a SQL task is
graded by generating a tiny Python driver that builds the task's schema in an
in-memory SQLite database, runs the learner's statement, and prints the rows as
JSON. The driver executes in the *same* locked-down Python sandbox as every other
submission, which means SQL practice inherits the isolation work for free.

The honest limits of that choice, so nobody discovers them the hard way:

* SQLite is not Postgres. Window functions and CTEs work; ``ILIKE``,
  ``DISTINCT ON`` and server-side types do not. A subject that teaches
  Postgres-specific SQL needs a Postgres runner, and that is a runtime addition,
  not a change to this grader.
* Only the final result set is compared. A submission that returns the right rows
  via a wildly inefficient plan passes; measuring plans is a separate dimension.

Comparison is set-based unless the task says ``ordered``, because a query without
``ORDER BY`` has no defined row order and marking it wrong for coming back
shuffled would be teaching the learner something false.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from learnos_schema import ExecutionRequest, SandboxLimits, SourceFile, SQLTask

from ..execution.service import ExecutionService, status_value
from .results import GradeOutcome, decide

DRIVER_FILENAME = "_learnos_sql_driver.py"
QUERY_FILENAME = "_learnos_query.sql"
SENTINEL = "__LEARNOS_SQL_V1__"

#: The driver. Reads the learner's SQL from a file rather than being generated
#: with it inlined, so a submission containing triple quotes or a null byte
#: cannot break the driver's own syntax, which would otherwise be an injection
#: into the grader.
_DRIVER = '''
import json, sqlite3, sys

SENTINEL = "{sentinel}"


def emit(payload):
    sys.stdout.write("\\n" + SENTINEL + " " + json.dumps(payload, default=str) + "\\n")
    sys.stdout.flush()


def main():
    with open("{query_file}", "r", encoding="utf-8") as handle:
        query = handle.read()

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        with open("_learnos_schema.sql", "r", encoding="utf-8") as handle:
            connection.executescript(handle.read())
        try:
            with open("_learnos_seed.sql", "r", encoding="utf-8") as handle:
                connection.executescript(handle.read())
        except FileNotFoundError:
            pass
    except sqlite3.Error as exc:
        emit({{"ok": False, "stage": "setup", "error": str(exc), "rows": None}})
        return 0

    try:
        cursor = connection.executescript(query) if ";" in query.strip()[:-1] else connection.execute(query)
    except sqlite3.Error as exc:
        emit({{"ok": False, "stage": "query", "error": str(exc), "rows": None}})
        return 0

    rows = None
    try:
        if cursor is not None and cursor.description is not None:
            rows = [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        emit({{"ok": False, "stage": "fetch", "error": str(exc), "rows": None}})
        return 0

    emit({{"ok": True, "stage": "done", "error": None, "rows": rows}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _driver_source() -> str:
    return _DRIVER.format(sentinel=SENTINEL, query_file=QUERY_FILENAME)


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


def _canonical(rows: Sequence[dict[str, Any]] | None) -> list[tuple[tuple[str, str], ...]]:
    """Rows as comparable tuples.

    Values are stringified before comparison because SQLite hands back ``1`` where
    an authored expectation might say ``1.0`` or ``"1"``, and failing a learner on
    the JSON type of a count is not a lesson about SQL.
    """
    if not rows:
        return []
    return [tuple(sorted((str(key), str(value)) for key, value in row.items())) for row in rows]


def compare_rows(
    actual: Sequence[dict[str, Any]] | None,
    expected: Sequence[dict[str, Any]] | None,
    *,
    ordered: bool,
) -> tuple[bool, str | None]:
    """Return ``(matches, reason)``. ``reason`` is learner-facing."""
    if expected is None:
        return True, None
    actual_rows = _canonical(actual)
    expected_rows = _canonical(expected)

    if ordered:
        if actual_rows == expected_rows:
            return True, None
    elif sorted(actual_rows) == sorted(expected_rows):
        return True, None

    if len(actual_rows) != len(expected_rows):
        return False, f"expected {len(expected_rows)} row(s), got {len(actual_rows)}"
    if sorted(actual_rows) == sorted(expected_rows) and ordered:
        return False, "the right rows, in the wrong order: this query needs an explicit ORDER BY"
    if actual and expected and set(actual[0]) != set(expected[0]):
        missing = sorted(set(expected[0]) - set(actual[0]))
        extra = sorted(set(actual[0]) - set(expected[0]))
        parts = []
        if missing:
            parts.append("missing column(s): " + ", ".join(missing))
        if extra:
            parts.append("unexpected column(s): " + ", ".join(extra))
        return False, "; ".join(parts)
    return False, "the row values do not match"


async def grade_sql(
    task: SQLTask,
    sql: str,
    *,
    execution: ExecutionService,
    execution_id: str | None = None,
) -> GradeOutcome:
    files = [
        SourceFile(path="_learnos_schema.sql", content=task.schema_sql, readonly=True),
        SourceFile(path=QUERY_FILENAME, content=sql),
        SourceFile(path=DRIVER_FILENAME, content=_driver_source(), readonly=True, hidden=True),
    ]
    if task.seed_sql:
        files.append(SourceFile(path="_learnos_seed.sql", content=task.seed_sql, readonly=True))

    # The authored environment says ``runtime: sql``; the driver is Python, so the
    # runtime is overridden while every *limit* the author set is preserved.
    limits = task.environment.model_copy(update={"runtime": "python", "runtime_version": None})
    if not isinstance(limits, SandboxLimits):  # pragma: no cover - defensive
        limits = SandboxLimits()

    outcome = await execution.execute(
        ExecutionRequest(files=files, limits=limits, command=f"python -I {DRIVER_FILENAME}"),
        execution_id=execution_id,
    )
    result = outcome.result
    payload = _parse(result.stdout)
    # The sentinel line is the grader's channel, not the learner's output.
    cleaned = "\n".join(line for line in result.stdout.splitlines() if not line.startswith(SENTINEL))
    result = result.model_copy(update={"stdout": cleaned})

    if payload is None:
        status = status_value(result)
        message = (
            "**Timed out.** The query was still running at the time limit."
            if status == "timeout"
            else "**The query could not be run.** Nothing was scored."
        )
        return GradeOutcome(score=0.0, passed=False, feedback_md=message, execution=result).clamped()

    if not payload.get("ok"):
        stage = str(payload.get("stage"))
        error = str(payload.get("error") or "unknown error")
        if stage == "setup":
            body = (
                "**The task's own schema failed to load**, so your query never ran. "
                "That is a content bug. Please report it.\n\n```\n" + error + "\n```"
            )
        else:
            body = "**SQLite rejected the statement:**\n\n```\n" + error + "\n```"
        return GradeOutcome(score=0.0, passed=False, feedback_md=body, execution=result).clamped()

    rows = payload.get("rows")
    matches, reason = compare_rows(rows, task.expected_result, ordered=bool(task.ordered))
    score, passed = decide(1.0 if matches else 0.0, task.evaluation)

    if passed:
        count = len(rows or [])
        feedback = f"**Correct.** {count} row(s) returned, matching the expected result."
    elif rows is None:
        feedback = (
            "**No result set.** The statement ran but returned no rows to compare: "
            "this task expects a `SELECT` that produces rows."
        )
    else:
        feedback = "**Not quite.** " + (reason or "the result does not match what the task asks for") + "."

    return GradeOutcome(score=score, passed=passed, feedback_md=feedback, execution=result).clamped()
