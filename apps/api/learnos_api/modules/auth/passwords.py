"""Password hashing.

bcrypt via passlib. bcrypt silently truncates at 72 bytes, so the input is capped
explicitly rather than left to the library: a 200-character passphrase whose
first 72 bytes match another user's would otherwise authenticate.
"""

from __future__ import annotations

from passlib.context import CryptContext

# rounds=12 is roughly 250ms on 2026 server hardware: slow enough to make offline
# cracking expensive, fast enough that login is not a timeout risk.
_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

BCRYPT_MAX_BYTES = 72


def _clamp(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) <= BCRYPT_MAX_BYTES:
        return password
    # Truncate on a byte boundary, then discard any partial multi-byte character.
    return encoded[:BCRYPT_MAX_BYTES].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    return _context.hash(_clamp(password))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _context.verify(_clamp(password), password_hash)
    except ValueError:
        # A malformed stored hash must fail closed, not raise a 500 that tells the
        # caller their account is special.
        return False


def needs_rehash(password_hash: str) -> bool:
    return _context.needs_update(password_hash)
