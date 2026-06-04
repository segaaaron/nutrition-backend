"""Push token entity (cross-platform)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Platform = Literal["web", "ios", "android"]


@dataclass(slots=True)
class PushToken:
    user_id: UUID
    platform: Platform
    token: str
    endpoint: str | None = None
    p256dh: str | None = None
    auth: str | None = None
    locale: str = "en"
    id: UUID | None = None
    created_at: datetime | None = None
    invalid_at: datetime | None = None
