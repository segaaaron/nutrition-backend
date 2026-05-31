"""Identity domain events. Frozen dataclasses subclass DomainEvent."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class UserRegistered(DomainEvent):
    user_id: UUID
    email: str
    at: datetime


@dataclass(frozen=True, slots=True)
class UserLoggedIn(DomainEvent):
    user_id: UUID
    at: datetime
    method: str  # 'password' | 'oauth_google' | 'oauth_apple' | 'otp'


@dataclass(frozen=True, slots=True)
class RefreshTokenIssued(DomainEvent):
    user_id: UUID
    token_id: UUID
    family_id: UUID
    at: datetime


@dataclass(frozen=True, slots=True)
class RefreshTokenReused(DomainEvent):
    """Security event — RFC 6819 §5.2.2.3. Triggers family-wide revocation."""

    user_id: UUID
    token_id: UUID
    family_id: UUID
    at: datetime


@dataclass(frozen=True, slots=True)
class OtpLocked(DomainEvent):
    user_id: UUID
    purpose: str
    locked_until: datetime


@dataclass(frozen=True, slots=True)
class UserDeletionScheduled(DomainEvent):
    user_id: UUID
    scheduled_for: datetime


@dataclass(frozen=True, slots=True)
class UserDeletionCancelled(DomainEvent):
    user_id: UUID
    at: datetime
