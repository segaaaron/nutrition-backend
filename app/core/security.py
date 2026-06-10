"""Auth + rate-limit primitives. Detailed JWT issuance lives in
`app.identity.infrastructure.jwt_service`; this module is intentionally thin.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    # Narrow exception surface: only argon2's own auth failures are expected.
    # Any other exception (TypeError on non-str input, etc.) must propagate
    # so we surface real bugs instead of silently returning "wrong password".
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
