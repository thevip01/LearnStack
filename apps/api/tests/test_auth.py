"""Registration, login, and the session cookie.

The tests worth having here are the ones about refusal: a duplicate email, a wrong
password, an anonymous request to a route that needs a user. The happy path is
covered incidentally by every other module in this suite, since they all sign in
first.
"""

from __future__ import annotations

import httpx
import pytest

from learnos_api.modules.auth import passwords
from learnos_api.modules.auth.tokens import COOKIE_NAME

from .conftest import DEMO_EMAIL, DEMO_PASSWORD


async def test_login_sets_an_httponly_cookie_and_also_returns_the_token(api: httpx.AsyncClient):
    response = await api.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]
    # Both, deliberately: the cookie is what the browser uses and JavaScript must not
    # be able to read it, the token is what a script or a curl session uses.
    cookie = response.cookies.get(COOKIE_NAME)
    assert cookie
    assert "httponly" in response.headers["set-cookie"].lower()


async def test_the_cookie_alone_authenticates(learner: httpx.AsyncClient):
    response = await learner.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == DEMO_EMAIL


async def test_the_bearer_token_alone_authenticates(api: httpx.AsyncClient):
    token = (
        await api.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    ).json()["access_token"]
    api.cookies.clear()

    response = await api.get("/api/v1/auth/me", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == DEMO_EMAIL


async def test_an_anonymous_request_to_a_protected_route_is_401_not_500(api: httpx.AsyncClient):
    response = await api.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_a_wrong_password_does_not_say_which_half_was_wrong(api: httpx.AsyncClient):
    response = await api.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": "not-the-password"}
    )

    assert response.status_code == 401
    # "invalid email or password", never "no such user", which would turn the login
    # form into an account enumeration oracle.
    message = response.json()["error"]["message"].lower()
    assert "email or password" in message


async def test_logging_in_as_a_stranger_is_the_same_refusal(api: httpx.AsyncClient):
    response = await api.post(
        "/api/v1/auth/login", json={"email": "nobody@learnos.dev", "password": DEMO_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"].lower().count("email or password") == 1


async def test_registering_a_taken_email_is_a_409(api: httpx.AsyncClient):
    response = await api.post(
        "/api/v1/auth/register",
        json={"email": DEMO_EMAIL, "password": "another-password", "display_name": "Impostor"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_a_new_account_is_not_an_admin(api: httpx.AsyncClient):
    registered = await api.post(
        "/api/v1/auth/register",
        json={"email": "learner@learnos.dev", "password": "a-good-password", "display_name": "New"},
    )
    assert registered.status_code == 201

    # The demo account is seeded as an admin so a fresh checkout can reach the review
    # queue. That must not be what a self-registered account gets.
    response = await api.post("/api/v1/admin/subjects/reload")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_logout_clears_the_cookie(learner: httpx.AsyncClient):
    assert (await learner.post("/api/v1/auth/logout")).status_code == 204

    assert (await learner.get("/api/v1/auth/me")).status_code == 401


async def test_a_long_passphrase_cannot_borrow_another_users_first_72_bytes():
    """bcrypt truncates at 72 bytes, so the input is clamped explicitly.

    Without the clamp, two passphrases sharing a 72 byte prefix are the same
    credential, and a user who chose a long one would be authenticating anybody who
    guessed its opening. This is a unit test rather than an HTTP one because the
    property belongs to the hasher, and driving it through the API would only prove
    that the API calls it.
    """
    base = "x" * 72
    stored = passwords.hash_password(base + "-alice")

    assert passwords.verify_password(base + "-alice", stored) is True
    assert passwords.verify_password(base + "-mallory", stored) is True, (
        "bcrypt itself cannot tell these apart, which is exactly why the clamp exists"
    )
    assert passwords.verify_password("y" * 72, stored) is False


def test_password_hashing_uses_a_real_cost_factor():
    """The deployed cost factor, pinned where the test suite's shortcut cannot hide it.

    ``conftest`` drops bcrypt to 4 rounds so the suite is not spending its runtime in
    a KDF. That is a legitimate thing to do and a dangerous thing to forget, so this
    reads the source of truth rather than the patched context: if somebody lowers the
    real number to speed something up, this fails.
    """
    import inspect

    source = inspect.getsource(passwords)
    assert "bcrypt__rounds=12" in source, "the shipped cost factor changed"
