"""What a 422 says, and the one banner claim that depends on the cache.

Two defects reported from a real local run, both of which were about a message
rather than about behaviour, and both of which a passing test suite had nothing to
say about:

1. Registering with an eight character password answered
   ``"message": "request body failed validation"``. True, unhelpful, and the only
   string the sign-in form displays. The rule (ten characters) and the field
   (password) were already in ``detail`` and nothing surfaced them.
2. The readiness banner ended every warning with "practice submissions may fail
   until service recovers", including when the only degraded dependency was
   Redis. Nothing on the submit path touches Redis.

So these tests are about wording, which is unusual and deliberate: an error a
learner cannot act on is a defect in the product even when the status code is
right, and a warning that is false teaches people to ignore warnings.
"""

from __future__ import annotations

import httpx
import pytest

from learnos_api.errors import validation_message
from learnos_api.schemas.auth import MIN_PASSWORD_LENGTH

from .conftest import ALL_CORRECT, QUIZ, REPO_ROOT, start_attempt, submit_quiz

REGISTER = "/api/v1/auth/register"


async def test_a_short_password_names_the_field_and_the_rule(api: httpx.AsyncClient):
    """The reported failure, as the learner met it."""
    response = await api.post(
        REGISTER, json={"email": "new@learnos.dev", "password": "8chars--"}
    )

    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert message == f"password must be at least {MIN_PASSWORD_LENGTH} characters", message


async def test_the_minimum_length_is_accepted(api: httpx.AsyncClient):
    """The boundary, so the rule the form now states is the rule the API applies.

    An off-by-one here would be worse than the original bug: the form would say ten
    characters, disable the button until ten, and then be refused at ten.
    """
    response = await api.post(
        REGISTER,
        json={"email": "boundary@learnos.dev", "password": "x" * MIN_PASSWORD_LENGTH},
    )

    assert response.status_code == 201, response.text


async def test_a_missing_field_says_it_is_required(api: httpx.AsyncClient):
    response = await api.post(REGISTER, json={"email": "new@learnos.dev"})

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "password is required"


async def test_a_validator_message_loses_pydantic_s_prefix(api: httpx.AsyncClient):
    """``ValueError("not a valid email address")`` reaches pydantic as
    ``"Value error, not a valid email address"``. The prefix means something to
    whoever wrote the validator and nothing to whoever typed the address."""
    response = await api.post(
        REGISTER, json={"email": "not-an-email", "password": "a-good-password"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "email: not a valid email address"


async def test_three_problems_report_two_and_count_the_rest(api: httpx.AsyncClient):
    """The cap is on the message, not on the response: ``detail`` stays complete.

    Two wrong fields is a person mis-filling a form and both are worth naming. A
    dozen is a client sending the wrong shape entirely, and that reader wants the
    structured list, not a paragraph.
    """
    response = await api.post(
        REGISTER,
        json={"email": "not-an-email", "password": "short", "display_name": "n" * 200},
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["message"] == (
        "email: not a valid email address; "
        f"password must be at least {MIN_PASSWORD_LENGTH} characters; "
        "and 1 more problem"
    ), body["message"]
    assert len(body["detail"]) == 3
    assert [entry["loc"] for entry in body["detail"]] == [
        ["body", "email"],
        ["body", "password"],
        ["body", "display_name"],
    ]


def test_a_query_parameter_is_named_as_one():
    """"limit" alone is ambiguous when a body field could be called the same thing.

    A unit test because provoking it through a route would pin the message to
    whichever endpoint happened to have an int query parameter today.
    """
    message = validation_message(
        [{"loc": ("query", "limit"), "msg": "Input should be a valid integer", "type": "int_parsing"}]
    )

    assert message == "query parameter limit: input should be a valid integer"


def test_a_nested_body_field_keeps_its_path():
    message = validation_message(
        [{"loc": ("body", "answers", "closures.shared-cell"), "msg": "Field required", "type": "missing"}]
    )

    assert message == "answers.closures.shared-cell is required"


def test_an_empty_error_list_still_produces_a_sentence():
    """Defensive: FastAPI has never handed over an empty list, and a message of ""
    would render as an empty red box with no text in it."""
    assert validation_message([]) == "request failed validation"


def test_the_register_form_states_the_password_rule():
    """The one number that lives in two languages.

    ``LoginView.tsx`` cannot import a Python constant, so it declares its own and
    this test is the pin. If somebody raises the server minimum to twelve, the form
    would go on promising ten and disabling the button at ten, and the learner would
    be refused by a rule nothing on screen mentions. That is the bug this whole file
    exists because of, so it gets a test rather than a comment.
    """
    view = REPO_ROOT / "apps" / "web" / "src" / "components" / "auth" / "LoginView.tsx"
    if not view.is_file():
        pytest.skip("no web app in this checkout")
    source = view.read_text(encoding="utf-8")

    assert f"const PASSWORD_MIN_LENGTH = {MIN_PASSWORD_LENGTH};" in source
    assert "`At least ${PASSWORD_MIN_LENGTH} characters.`" in source
    assert "minLength={intent === \"register\" ? PASSWORD_MIN_LENGTH : undefined}" in source


async def test_a_submission_still_works_with_the_cache_unreachable(learner: httpx.AsyncClient):
    """The claim the readiness banner used to make, tested.

    ``REDIS_URL`` in this suite points at a closed port, so every test here runs
    cache-down; this one says so out loud because a UI string depends on it. Redis
    backs progress-rollup caching, subject-runtime caching and the rate-limit
    windows, and all three fail open, so an attempt, a submission, the evidence it
    writes and the mastery it moves are all unaffected. The banner now says only
    what is true of the dependency that is actually down.
    """
    assert (await learner.get("/readyz")).json()["redis"] is False

    attempt = await start_attempt(learner, QUIZ)
    result = await submit_quiz(learner, attempt, ALL_CORRECT)

    assert result["score"] == 1.0
    assert result["passed"] is True
