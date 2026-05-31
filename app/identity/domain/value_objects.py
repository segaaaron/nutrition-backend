"""Identity value objects. Frozen + validated at construction."""
from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True, slots=True)
class Email:
    value: str

    def __post_init__(self) -> None:
        if not _EMAIL_RE.match(self.value):
            raise ValueError(f"invalid email: {self.value!r}")

    @property
    def normalized(self) -> str:
        return self.value.strip().lower()


@dataclass(frozen=True, slots=True)
class PasswordHash:
    """Wrapper signalling 'this is a hash, not plaintext'."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("$argon2"):
            raise ValueError("PasswordHash must be argon2-encoded")


@dataclass(frozen=True, slots=True)
class Token:
    """Opaque refresh token. Plaintext only crosses the network once."""

    value: str

    def __post_init__(self) -> None:
        if len(self.value) < 32:
            raise ValueError("Token too short")
