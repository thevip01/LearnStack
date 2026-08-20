"""JWT issue and verify.

HS256 with a shared secret. Asymmetric signing buys nothing here because the only
verifier is this service; when a second service needs to verify tokens, that is
the moment to move to RS256, not before.

The token carries ``is_admin`` so that admin routes do not need a database read to
reject a non-admin. It is re-checked against the row for anything destructive, so
a demoted admin cannot use an unexpired token to keep writing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ...errors import Unauthorized

ALGORITHM = "HS256"
ISSUER = "learnos-api"
COOKIE_NAME = "learnos_session"


def issue_token(
    *,
    user_id: uuid.UUID | str,
    email: str,
    is_admin: bool,
    secret: str,
    expires_minutes: int,
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    now = datetime.now(timezone.utc)
    expires_in = expires_minutes * 60
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "adm": is_admin,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM), expires_in


def decode_token(token: str, secret: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("session expired") from exc
    except jwt.InvalidTokenError as exc:
        # Never echo the library's reason: "signature verification failed" versus
        # "invalid issuer" is a probing oracle.
        raise Unauthorized("invalid credentials") from exc


def user_id_from_payload(payload: dict[str, Any]) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise Unauthorized("invalid credentials") from exc
