"""Coach domain events."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class MessageSent(DomainEvent):
    conv_id: UUID
    user_id: UUID
    intent: str
    at: datetime


@dataclass(frozen=True, slots=True)
class MessageReceived(DomainEvent):
    conv_id: UUID
    user_id: UUID
    intent: str
    tokens_in: int
    tokens_out: int
    camino: str  # template | cached | mini | refuse
    at: datetime


@dataclass(frozen=True, slots=True)
class IntentDetected(DomainEvent):
    user_id: UUID
    intent: str
    confidence: float
    at: datetime
