"""Auth + rate-limit primitives. Detailed JWT issuance lives in
`app.identity.infrastructure.jwt_service`; this module is intentionally thin.
"""

from __future__ import annotations

from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except Exception:
        return False
