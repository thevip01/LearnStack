#!/usr/bin/env python3
"""Test harness that runs *inside* the sandbox container.

This file is copied into the workspace by the runner (see
``learnos_sandbox.protocol.harness_source``) and executed instead of pytest
directly. It exists for three reasons, in order of importance:

1. **It stops pytest's terminal output reaching the client.** pytest prints the
   source of a failing assertion, which for a hidden test *is the answer*. The
   harness captures every byte pytest writes and emits only a structured report;
   what the learner is allowed to see is then decided by the API's grader, which
   is the one place that knows which tests are visible.
2. **It maps pytest node ids back onto authored ``TestCase.id`` values.** Scoring
   is weighted per authored test, so ``tests/test_x.py::test_empty`` has to
   become ``t2`` before any arithmetic happens. Guessing that mapping in the API
   from a string match against captured output would be fragile; doing it here,
   next to the real node ids, is not.
3. **It makes a crash legible.** A collection error or an import failure is
   reported as structured data naming the *file*, never the file's contents.

Constraints this file lives under, which explain its shape:

* stdlib + pytest only. The runner image ships nothing else, deliberately.
* No import of ``learnos_sandbox``: that package is not in the container. The
  sentinel and manifest names below are therefore duplicated from
  ``protocol.py``; ``tests/test_sandbox_protocol.py`` asserts the two agree so
  the duplication cannot silently drift.
* Exit status describes *the harness*, not the learner's tests. Failing tests are
  a successful run that reports failures; a non-zero exit means pytest could not
  be driven at all.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from contextlib import redirect_stderr, redirect_stdout

# Duplicated from learnos_sandbox.protocol on purpose; see the module docstring.
RESULT_SENTINEL = "__LEARNOS_RESULT_V1__"
MANIFEST_FILENAME = "_learnos_tests.json"

#: Failure text is for a human reading a diff, not a data channel. Anything
#: longer than this is a runaway repr and gets cut.
MESSAGE_LIMIT = 4000
STDOUT_LIMIT = 4000

_PARAM_RE = re.compile(r"\[.*\]$")


def _truncate(text, limit=MESSAGE_LIMIT):
    if text is None:
        return None
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


def _load_manifest():
    """Read the authored-test manifest, if the runner supplied one."""
    if not os.path.exists(MANIFEST_FILENAME):
        return None
    try:
        with open(MANIFEST_FILENAME, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _node_file(node_id):
    return node_id.split("::", 1)[0]


def _node_functions(node_id):
    """Every ``::`` segment after the file, with parametrisation suffixes removed."""
    parts = node_id.split("::")[1:]
    return [_PARAM_RE.sub("", part) for part in parts]


class _Collector:
    """Inline pytest plugin used when ``pytest-json-report`` is unavailable.

    Kept as a fallback so a runner image built without the plugin still produces
    a usable report rather than failing every submission with a usage error.
    """

    def __init__(self):
        self.nodes = {}
        self.collect_errors = []

    def _entry(self, node_id):
        return self.nodes.setdefault(
            node_id,
            {
                "node_id": node_id,
                "outcome": "passed",
                "duration_ms": 0.0,
                "message": None,
                "stdout": "",
                "stderr": "",
            },
        )

    # pytest hook
    def pytest_runtest_logreport(self, report):
        entry = self._entry(report.nodeid)
        entry["duration_ms"] += float(getattr(report, "duration", 0.0)) * 1000.0
        captured = getattr(report, "capstdout", "") or ""
        if captured:
            entry["stdout"] = (entry["stdout"] + captured)[:STDOUT_LIMIT]
        captured_err = getattr(report, "capstderr", "") or ""
        if captured_err:
            entry["stderr"] = (entry["stderr"] + captured_err)[:STDOUT_LIMIT]
        if report.failed:
            # A failure outside the call phase is a broken fixture or import,
            # which is a different thing to a wrong answer and is labelled so.
            entry["outcome"] = "failed" if report.when == "call" else "error"
            if entry["message"] is None and report.longrepr is not None:
                entry["message"] = _truncate(report.longrepr)
        elif report.skipped and entry["outcome"] == "passed":
            entry["outcome"] = "skipped"

    # pytest hook
    def pytest_collectreport(self, report):
        if report.failed:
            self.collect_errors.append(
                {
                    "file": _node_file(str(report.nodeid)),
                    "message": _truncate(report.longrepr, 1500),
                }
            )


def _json_report_available():
    try:
        import pytest_jsonreport  # noqa: F401
    except Exception:
        return False
    return True


def _nodes_from_json_report(path):
    """Normalise a ``pytest-json-report`` file into the collector's node shape."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None, []

    nodes = {}
    for test in data.get("tests", []) or []:
        node_id = test.get("nodeid")
        if not node_id:
            continue
        outcome = test.get("outcome", "failed")
        duration = 0.0
        message = None
        stdout = ""
        stderr = ""
        for stage in ("setup", "call", "teardown"):
            info = test.get(stage) or {}
            duration += float(info.get("duration", 0.0) or 0.0)
            stdout += info.get("stdout", "") or ""
            stderr += info.get("stderr", "") or ""
            if message is None and info.get("longrepr"):
                message = info["longrepr"]
            if message is None and info.get("traceback"):
                message = json.dumps(info["traceback"])[:MESSAGE_LIMIT]
        if outcome == "failed" and (test.get("call") or {}).get("outcome") != "failed":
            outcome = "error"
        nodes[node_id] = {
            "node_id": node_id,
            "outcome": outcome,
            "duration_ms": duration * 1000.0,
            "message": _truncate(message),
            "stdout": stdout[:STDOUT_LIMIT],
            "stderr": stderr[:STDOUT_LIMIT],
        }

    collect_errors = []
    for collector in data.get("collectors", []) or []:
        if collector.get("outcome") == "failed":
            collect_errors.append(
                {
                    "file": _node_file(str(collector.get("nodeid", ""))),
                    "message": _truncate(collector.get("longrepr"), 1500),
                }
            )
    return nodes, collect_errors


def _match_nodes(spec, nodes):
    """Find the pytest nodes belonging to one authored test.

    Four strategies, most specific first. Parametrised tests legitimately map one
    authored test onto several nodes, so this returns a list.
    """
    node_ids = list(nodes)

    explicit = spec.get("node_id")
    if explicit:
        exact = [n for n in node_ids if n == explicit or n.startswith(explicit + "[")]
        if exact:
            return exact

    wanted_file = spec.get("file")
    functions = [f for f in (spec.get("functions") or []) if f]

    if wanted_file and functions:
        matched = [n for n in node_ids if _node_file(n) == wanted_file and set(functions) & set(_node_functions(n))]
        if matched:
            return matched

    if functions:
        matched = [n for n in node_ids if set(functions) & set(_node_functions(n))]
        if matched:
            return matched

    if wanted_file:
        matched = [n for n in node_ids if _node_file(n) == wanted_file]
        if len(matched) == 1:
            return matched

    return []


def _aggregate(spec, matched, nodes):
    """Collapse the nodes of one authored test into a single result."""
    if not matched:
        return {
            "test_id": spec.get("id"),
            "name": spec.get("name"),
            "weight": float(spec.get("weight", 1.0) or 1.0),
            "matched": False,
            "passed": False,
            "status": "not_run",
            "duration_ms": 0,
            "message": "test did not run",
            "stdout": "",
            "node_ids": [],
        }
    outcomes = [nodes[n]["outcome"] for n in matched]
    duration = sum(nodes[n]["duration_ms"] for n in matched)
    failing = [n for n in matched if nodes[n]["outcome"] not in ("passed",)]
    if not failing:
        status = "passed"
    elif any(nodes[n]["outcome"] == "error" for n in failing):
        status = "error"
    elif all(o == "skipped" for o in outcomes):
        status = "skipped"
    else:
        status = "failed"
    message = None
    stdout = ""
    for node in failing or matched:
        if message is None:
            message = nodes[node]["message"]
        stdout += nodes[node].get("stdout") or ""
    return {
        "test_id": spec.get("id"),
        "name": spec.get("name"),
        "weight": float(spec.get("weight", 1.0) or 1.0),
        "matched": True,
        # A skipped test is not a pass. Scoring it as one would let a learner
        # earn mastery by adding a skip marker.
        "passed": status == "passed",
        "status": status,
        "duration_ms": int(duration),
        "message": _truncate(message),
        "stdout": stdout[:STDOUT_LIMIT],
        "node_ids": sorted(matched),
    }


def _pytest_args(manifest, report_path):
    args = ["-q", "-p", "no:cacheprovider", "--tb=short", "-rN", "--color=no", "--continue-on-collection-errors"]
    if report_path is not None:
        args += [
            "--json-report",
            "--json-report-file=" + report_path,
            "--json-report-omit=keywords,log,warnings",
        ]
    targets = []
    if manifest:
        targets = list(manifest.get("targets") or [])
        if not targets:
            seen = []
            for spec in manifest.get("tests") or []:
                path = spec.get("file")
                if path and path not in seen and os.path.exists(path):
                    seen.append(path)
            targets = seen
    return args + targets


def main():
    manifest = _load_manifest()
    report_path = "_learnos_report.json" if _json_report_available() else None
    collector = _Collector()
    args = _pytest_args(manifest, report_path)

    started = time.time()
    buffer = io.StringIO()
    err_buffer = io.StringIO()
    exit_code = 3
    try:
        import pytest
    except Exception as exc:  # pragma: no cover - image misconfiguration
        _emit(
            {
                "schema": 1,
                "ok": False,
                "error": "pytest is not installed in the runner image: %s" % exc,
                "tests": [],
                "totals": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            }
        )
        return 3

    # Everything pytest writes goes into a buffer that is never returned
    # verbatim when a manifest is present. This redirect is the actual mechanism
    # that keeps hidden assertion text out of the HTTP response.
    with redirect_stdout(buffer), redirect_stderr(err_buffer):
        try:
            exit_code = int(pytest.main(args, plugins=[collector]))
        except SystemExit as exc:  # pytest.main should not, but be certain
            exit_code = int(exc.code or 0)
        except BaseException as exc:  # noqa: BLE001 - must still emit a report
            exit_code = 3
            print("harness error: %r" % (exc,))

    nodes = collector.nodes
    collect_errors = list(collector.collect_errors)
    if report_path is not None:
        parsed, parsed_errors = _nodes_from_json_report(report_path)
        if parsed:
            nodes = parsed
            collect_errors = parsed_errors or collect_errors

    results = []
    claimed = set()
    if manifest:
        for spec in manifest.get("tests") or []:
            matched = _match_nodes(spec, nodes)
            claimed.update(matched)
            results.append(_aggregate(spec, matched, nodes))
    else:
        for node_id in sorted(nodes):
            spec = {"id": node_id, "name": node_id.split("::")[-1], "weight": 1.0}
            results.append(_aggregate(spec, [node_id], nodes))
            claimed.add(node_id)

    # Nodes pytest ran that no authored test claims. Reported by node id only:
    # useful for spotting a bad manifest, worthless as an answer key.
    extra = [
        {"node_id": node_id, "status": nodes[node_id]["outcome"]} for node_id in sorted(nodes) if node_id not in claimed
    ]

    payload = {
        "schema": 1,
        "ok": True,
        "pytest_exit_code": exit_code,
        "duration_ms": int((time.time() - started) * 1000),
        "tests": results,
        "extra_tests": extra,
        "collect_errors": collect_errors,
        "totals": {
            "total": len(results),
            "passed": sum(1 for r in results if r["passed"]),
            "failed": sum(1 for r in results if not r["passed"] and r["status"] in ("failed", "error")),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "not_run": sum(1 for r in results if r["status"] == "not_run"),
        },
    }
    if manifest is None:
        # No authored tests means no hidden material, so the terminal output is
        # safe to hand back and is genuinely useful for an ad-hoc run.
        payload["pytest_output"] = _truncate(buffer.getvalue(), 8000)
        payload["pytest_stderr"] = _truncate(err_buffer.getvalue(), 4000)

    _emit(payload)

    # Exit codes: 0 whenever a report was produced (failing tests included, they
    # are data). 5 means pytest collected nothing, which the grader treats as a
    # broken task rather than a wrong answer.
    if exit_code in (0, 1):
        return 0
    return exit_code


def _emit(payload):
    """Write the one structured line, on the real stdout, and flush."""
    line = RESULT_SENTINEL + " " + json.dumps(payload, default=str)
    stream = sys.__stdout__ or sys.stdout
    stream.write("\n" + line + "\n")
    stream.flush()


if __name__ == "__main__":
    sys.exit(main())
