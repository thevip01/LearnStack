"""Registration, login and the session cookie."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from ...config import Settings
from ...errors import Conflict, Unauthorized
from ...logging import get_logger
from ...models import User
from ...schemas.auth import AuthOut, UserOut
from .passwords import hash_password, verify_password
from .tokens import COOKIE_NAME, issue_token

log = get_logger(__name__)


def user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        is_admin=user.is_admin,
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None,
    settings: Settings,
    is_admin: bool = False,
) -> tuple[User, AuthOut]:
    if await get_user_by_email(session, email) is not None:
        raise Conflict("an account with that email already exists")

    user = User(
        id=uuid.uuid4(),
        email=email.strip().lower(),
        display_name=(display_name or email.split("@")[0]).strip()[:120],
        password_hash=hash_password(password),
        is_admin=is_admin,
    )
    session.add(user)
    # Flush so ``created_at`` is populated by the server default before we build the
    # response body from it.
    await session.flush()
    await session.refresh(user)
    log.info("user_registered", user_id=str(user.id))
    return user, _auth_out(user, settings)


async def login(session: AsyncSession, *, email: str, password: str, settings: Settings) -> tuple[User, AuthOut]:
    user = await get_user_by_email(session, email)
    # Verify against a dummy hash when the account does not exist so that the
    # response time does not distinguish "no such user" from "wrong password".
    stored = user.password_hash if user else _DUMMY_HASH
    ok = verify_password(password, stored)
    if user is None or not ok or not user.is_active:
        raise Unauthorized("invalid email or password")

    user.last_login_at = datetime.now(timezone.utc)
    return user, _auth_out(user, settings)


def _auth_out(user: User, settings: Settings) -> AuthOut:
    token, expires_in = issue_token(
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        secret=settings.JWT_SECRET,
        expires_minutes=settings.JWT_EXPIRES_MINUTES,
    )
    return AuthOut(access_token=token, token_type="bearer", expires_in=expires_in, user=user_out(user))


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """httpOnly cookie for the browser; the same token is in the body for scripts.

    ``SameSite=Lax`` is what the contract specifies. It stops the cookie riding
    along on cross-site POSTs, which is the CSRF vector that matters for a
    cookie-authenticated write API.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.JWT_EXPIRES_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


# A real bcrypt hash of a value nobody knows, used only to equalise login timing.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.rG7RgvSNCJXyZ0YQ.7t9lQZ8w8Vv1Zu"
