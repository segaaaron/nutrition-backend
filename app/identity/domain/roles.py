"""RBAC role hierarchy (OWASP API5 — Broken Function Level Authorization).

Roles are a strict total order:
    user < premium < support < admin

`role_at_least(claim, required)` returns True iff `claim` role is >= `required`.
Endpoints declare minimum required role; deps enforce via JWT claim.

Roles are versioned: never delete a role, only deprecate. Storing the string
in JWT keeps tokens portable across schema changes.
"""
from __future__ import annotations

from enum import IntEnum


class Role(IntEnum):
    USER = 0
    PREMIUM = 10
    SUPPORT = 20
    ADMIN = 100

    @classmethod
    def from_str(cls, value: str) -> "Role":
        try:
            return _STR_TO_ROLE[value.lower()]
        except KeyError as e:
            raise ValueError(f"unknown role: {value!r}") from e

    def to_str(self) -> str:
        return _ROLE_TO_STR[self]


_STR_TO_ROLE: dict[str, Role] = {
    "user": Role.USER,
    "premium": Role.PREMIUM,
    "support": Role.SUPPORT,
    "admin": Role.ADMIN,
}

_ROLE_TO_STR: dict[Role, str] = {v: k for k, v in _STR_TO_ROLE.items()}

VALID_ROLE_STRINGS: frozenset[str] = frozenset(_STR_TO_ROLE.keys())


def role_at_least(claim_role: str, required: Role) -> bool:
    """Returns True iff `claim_role` (string from JWT) is >= `required`."""
    try:
        claim = Role.from_str(claim_role)
    except ValueError:
        return False
    return claim >= required
