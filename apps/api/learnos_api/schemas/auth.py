"""Auth envelopes."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from .common import ApiModel, UtcDatetime

#: The contract's minimum. Enforced here rather than in the hashing layer so the
#: error the learner sees is a validation error on the field they typed in.
MIN_PASSWORD_LENGTH = 10

# Deliberately not ``pydantic.EmailStr``: that pulls in ``email-validator``, and
# an extra runtime dependency to reject "a@b" is not worth it. Deliverability is
# proven by a confirmation mail, which is phase 2; this only rejects obvious junk.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def normalise_email(value: str) -> str:
    """Lowercase and strip. The local part is technically case sensitive; treating
    it as insensitive prevents two accounts that look identical to a human."""
    cleaned = value.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("not a valid email address")
    return cleaned


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        return normalise_email(value)

    @field_validator("password")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password cannot be blank")
        return value


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        # Login must not reject on format: an existing account with an address this
        # regex would refuse still has to be able to sign in.
        return value.strip().lower()


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str
    created_at: UtcDatetime
    is_admin: bool


class AuthOut(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
