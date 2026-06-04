"""Identity domain entities. Framework-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

OtpPurpose = Literal["register", "reset", "login"]


@dataclass(slots=True)
class User:
    id: UUID
    email: str
    password_hash: str | None
    oauth_provider: str | None
    oauth_subject: str | None
    email_verified: bool
    role: str
    created_at: datetime
    last_login_at: datetime | None = None
    deletion_requested_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(slots=True)
class RefreshToken:
    id: UUID
    user_id: UUID
    token_hash: str
    family_id: UUID
    parent_id: UUID | None
    expires_at: datetime
    revoked_at: datetime | None = None
    reused_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass(slots=True)
class OtpCode:
    id: UUID
    user_id: UUID
    code_hash: str
    purpose: OtpPurpose
    expires_at: datetime
    attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )

    def is_locked(self, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > now
