"""Coach domain entities — Conversation aggregate + Message value object."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.coach.domain.value_objects import Role


@dataclass(slots=True)
class Message:
    id: UUID = field(default_factory=uuid4)
    conv_id: UUID = field(default_factory=uuid4)
    role: Role = Role.USER
    content: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    prompt_sha256: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class Conversation:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID | None = None
    title: str | None = None
    locale: str = "en"
    created_at: datetime | None = None
    messages: list[Message] = field(default_factory=list)
