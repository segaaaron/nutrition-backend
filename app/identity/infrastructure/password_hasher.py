"""argon2id password hasher.

Tuned to t=3, m=64MiB, p=1 per spec §12. The default `argon2.PasswordHasher`
already uses these as defaults (argon2-cffi 23.x), but we pin them explicitly
so future library upgrades don't silently change the work factor.
"""
from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import VerifyMismatchError


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = _Argon2(
            time_cost=3,
            memory_cost=64 * 1024,  # KiB → 64 MiB
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, plain: str) -> str:
        return self._hasher.hash(plain)

    def verify(self, plain: str, hashed: str) -> bool:
        try:
            return self._hasher.verify(hashed, plain)
        except (VerifyMismatchError, Exception):
            return False
