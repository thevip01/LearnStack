"""Authentication dependencies.

Three flavours, because the contract needs three:

* ``current_user``: required. 401 otherwise.
* ``current_user_optional``: the *(auth optional)* endpoints. Returns ``None``
  anonymously so the catalogue and lesson bodies render without a signup wall.
* ``current_admin``: required and re-checked against the database row, so a
  demoted admin's unexpired token stops working immediately.

Credentials come from the ``Authorization: Bearer`` header or the
``learnos_session`` cookie, header first. Browsers use the cookie, scripts use the
header, and both hit the same code path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings, get_settings
from ...db import get_session
from ...errors import Forbidden, Unauthorized
from ...models import User
from .service import get_user_by_id
from .tokens import COOKIE_NAME, decode_token, user_id_from_payload

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        # A malformed Authorization header is an error the caller should see rather
        # than a silent fall through to the cookie.
        raise Unauthorized("Authorization header must be 'Bearer <token>'")
    cookie = request.cookies.get(COOKIE_NAME)
    return cookie.strip() if cookie else None


async def current_user_optional(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> User | None:
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token, settings.JWT_SECRET)
    user = await get_user_by_id(session, user_id_from_payload(payload))
    if user is None or not user.is_active:
        raise Unauthorized("account no longer active")
    return user


async def current_user(
    user: Annotated[User | None, Depends(current_user_optional)],
) -> User:
    if user is None:
        raise Unauthorized()
    return user


async def current_admin(
    user: Annotated[User, Depends(current_user)],
) -> User:
    if not user.is_admin:
        raise Forbidden("administrator access required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(current_user_optional)]
CurrentAdmin = Annotated[User, Depends(current_admin)]
