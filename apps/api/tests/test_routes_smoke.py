"""Every GET route answers, and no concept detail 500s.

This file exists because of a bug that every offline gate was structurally unable
to see. ``ConceptOut`` subclasses ``Concept`` and narrows ``practice`` from a list
of task ids to a list of summaries. The assembler built it with
``ConceptOut(**concept.model_dump(), practice=...)``, so Python raised
``TypeError: got multiple values for keyword argument 'practice'`` and the route
returned 500 for *every* concept in *every* subject.

Nothing in `make check` could catch it. ``check_contract`` compares field names
between the API and the web client, and the field names were right. ``check_imports``
resolves symbols, and every symbol resolved. ``tsc`` typechecks the client, and the
client was fine. ``verify_loop.sh`` drives learn to practice to grade, and it never
fetched a concept body. The bug needed exactly one thing to surface: calling the
route. A browser found it in about four seconds.

So there are two tests here, one narrow and one wide.

``test_concept_detail_renders`` is parametrised over every concept file on disk and
asserts the shape the lesson view depends on, including that ``practice`` really did
become summaries. It is the direct regression test.

``test_get_route_has_no_server_error`` walks ``app.routes`` instead of a hand written
list, so a route added later is covered the day it is added rather than the day
someone remembers to add it here. It asserts only the absence of 500, which is a low
bar on purpose: a 401 on an admin route and a 404 on a run id that was never created
are both correct answers, and pinning bodies here would duplicate the focused suites.
Routes whose path parameters name a runtime created object are still requested, with
a syntactically valid id that does not exist, because "missing row" must be a 404 and
not an unhandled ``None``.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import httpx
import pytest

from learnos_api.schemas.practice import PracticeState

from .conftest import CODE, DEBUG, QUIZ, SKILL, SUBJECT, SUBJECTS_DIR

CONCEPT_DIR = SUBJECTS_DIR / "programming" / "python" / "concepts"

#: Read off the contract rather than retyped, so adding a state does not need an
#: edit here and removing one fails loudly.
PRACTICE_STATES = set(typing.get_args(PracticeState))


def concept_ids() -> list[str]:
    if not CONCEPT_DIR.is_dir():
        return []
    ids = []
    for path in sorted(CONCEPT_DIR.glob("*.json")):
        body = json.loads(Path(path).read_text())
        if body.get("id"):
            ids.append(body["id"])
    return ids


#: An id that is syntactically fine and deliberately absent, for the routes whose
#: parameter names a row created at runtime. The right answer is 404.
ABSENT = "00000000-0000-4000-8000-000000000000"

PARAMS = {
    "subject_id": SUBJECT,
    "concept_id": concept_ids()[0] if concept_ids() else "missing",
    "skill_id": SKILL,
    "task_id": QUIZ,
    "run_id": ABSENT,
    "execution_id": ABSENT,
    "entity_id": SUBJECT,
}

#: Routes that need a query string to do anything but 422. Supplied so the sweep
#: exercises the handler rather than the validator.
QUERY = {
    "/api/v1/search": {"q": "closure", "subject_id": SUBJECT},
    "/api/v1/compare": {"ids": [concept_ids()[0], concept_ids()[1]] if len(concept_ids()) > 1 else []},
}


def get_routes(app) -> list[str]:
    """Every GET path in the app, with parameters filled in."""
    paths: list[str] = []
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if "GET" not in methods or not path:
            continue
        if path in {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}:
            continue
        filled = path
        for name, value in PARAMS.items():
            filled = filled.replace("{" + name + "}", value)
        if "{" in filled:  # a parameter this map does not know about
            paths.append(path)  # keep it, so the assertion below reports it
            continue
        paths.append(filled)
    return sorted(set(paths))


@pytest.mark.subjects
@pytest.mark.parametrize("concept_id", concept_ids())
async def test_concept_detail_renders(learner: httpx.AsyncClient, concept_id: str) -> None:
    """The lesson payload builds for every authored concept."""
    response = await learner.get(f"/api/v1/subjects/{SUBJECT}/concepts/{concept_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["id"] == concept_id
    # The narrowed field. Before the fix this route raised TypeError; the assertion
    # that matters is that these are summaries, not the authored list of ids.
    assert isinstance(body["practice"], list)
    for item in body["practice"]:
        assert isinstance(item, dict), f"practice item is {type(item).__name__}, not a summary"
        assert item["id"]
        assert item["title"]
        assert item["state"] in PRACTICE_STATES
    # The runtime additions the lesson view reads.
    assert isinstance(body["prerequisite_status"], list)
    assert "next_concept_id" in body and "prev_concept_id" in body
    assert body["module"] is None or body["module"]["track_id"]


@pytest.mark.subjects
async def test_concept_detail_practice_matches_the_authored_order(
    learner: httpx.AsyncClient,
) -> None:
    """Summaries come back in the order the concept authored them.

    Worth pinning separately: the fix drops ``practice`` from the model dump, and a
    future refactor that rebuilt the list from the package's own dict would silently
    reorder it. The lesson view renders these top to bottom.
    """
    target = None
    for path in sorted(CONCEPT_DIR.glob("*.json")):
        body = json.loads(path.read_text())
        if len(body.get("practice") or []) > 1:
            target = body
            break
    if target is None:
        pytest.skip("no concept has more than one attached practice task")

    response = await learner.get(f"/api/v1/subjects/{SUBJECT}/concepts/{target['id']}")
    assert response.status_code == 200, response.text
    returned = [item["id"] for item in response.json()["practice"]]
    assert returned == [t for t in target["practice"] if t in set(returned)]


@pytest.mark.subjects
async def test_get_route_has_no_server_error(learner: httpx.AsyncClient) -> None:
    """No GET route in the app answers 500 for a real id or a missing one."""
    app = learner.app  # type: ignore[attr-defined]
    unfilled = [p for p in get_routes(app) if "{" in p]
    assert not unfilled, f"add these parameters to PARAMS: {unfilled}"

    failures: list[str] = []
    checked = 0
    for path in get_routes(app):
        params = QUERY.get(path)
        response = await learner.get(path, params=params)
        checked += 1
        if response.status_code >= 500:
            failures.append(f"{path} -> {response.status_code} {response.text[:200]}")

    assert not failures, "server errors:\n" + "\n".join(failures)
    # A floor, so a router that silently stops being mounted shows up as a failure
    # here rather than as a suite that quietly checks nothing.
    assert checked >= 15, f"only {checked} GET routes discovered, expected at least 15"


@pytest.mark.subjects
@pytest.mark.parametrize("task_id", [QUIZ, CODE, DEBUG])
async def test_practice_detail_renders(learner: httpx.AsyncClient, task_id: str) -> None:
    """Each authored task's learner-facing payload builds."""
    response = await learner.get(f"/api/v1/practice/{task_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == task_id
    assert body["title"]
