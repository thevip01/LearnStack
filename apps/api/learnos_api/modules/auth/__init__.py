"""Authentication: passwords, tokens, dependencies and rate limits."""

from __future__ import annotations

from .deps import CurrentAdmin, CurrentUser, OptionalUser, SessionDep, SettingsDep
from .passwords import hash_password, verify_password
from .ratelimit import ADHOC_EXECUTION_LIMIT, LOGIN_LIMIT, REGISTER_LIMIT, Limit, enforce
from .service import (
    clear_session_cookie,
    get_user_by_email,
    get_user_by_id,
    login,
    register,
    set_session_cookie,
    user_out,
)
from .tokens import COOKIE_NAME, decode_token, issue_token

__all__ = [
    "ADHOC_EXECUTION_LIMIT",
    "COOKIE_NAME",
    "CurrentAdmin",
    "CurrentUser",
    "LOGIN_LIMIT",
    "Limit",
    "OptionalUser",
    "REGISTER_LIMIT",
    "SessionDep",
    "SettingsDep",
    "clear_session_cookie",
    "decode_token",
    "enforce",
    "get_user_by_email",
    "get_user_by_id",
    "hash_password",
    "issue_token",
    "login",
    "register",
    "set_session_cookie",
    "user_out",
    "verify_password",
]
