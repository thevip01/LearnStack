"""Auth routes.

Both register and login set the httpOnly cookie *and* return the token in the
body. That is not redundancy: a browser should never hold a JWT in JavaScript
where an XSS can read it, and a script has no cookie jar. One endpoint serving
both keeps the frontend from needing a second auth path.

The rate limits are keyed on the client IP rather than the email, because keying
on the email lets an attacker lock a known account out by spending their
allowance for them.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ..modules.auth import deps as auth_deps
from ..modules.auth import ratelimit, service
from ..modules.auth.tokens import COOKIE_NAME
from ..schemas.auth import AuthOut, LoginIn, RegisterIn, UserOut
from .deps import SessionDep, SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    ``X-Forwarded-For`` is trusted only for its first hop and only because this
    service is expected to sit behind a proxy it controls. It is a rate-limit key,
    not an authorisation input, so a spoofed value costs an attacker their own
    bucket rather than granting them anything.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthOut:
    await ratelimit.enforce(ratelimit.REGISTER_LIMIT, _client_ip(request))
    _, out = await service.register(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        settings=settings,
    )
    service.set_session_cookie(response, out.access_token, settings)
    return out


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthOut:
    await ratelimit.enforce(ratelimit.LOGIN_LIMIT, _client_ip(request))
    _, out = await service.login(session, email=body.email, password=body.password, settings=settings)
    service.set_session_cookie(response, out.access_token, settings)
    return out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> Response:
    """Clear the cookie.

    Deliberately does not require authentication and deliberately does not
    blacklist the token. A logout that 401s because the token already expired is
    a logout that leaves the cookie behind, and server-side revocation needs a
    token store this phase does not have, so bearer tokens stay valid until they
    expire, which is why ``JWT_EXPIRES_MINUTES`` is a week and not a month.
    """
    service.clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    # Belt and braces: some proxies drop Set-Cookie on a 204 with no body, so
    # send the expiry header on an explicit response object.
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/me", response_model=UserOut)
async def me(user: auth_deps.CurrentUser) -> UserOut:
    return service.user_out(user)
