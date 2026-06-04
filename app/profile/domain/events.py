"""Profile domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class OnboardingCompleted(DomainEvent):
    user_id: UUID
    at: datetime


@dataclass(frozen=True, slots=True)
class BiometricsChanged(DomainEvent):
    """Fired when weight / height / age / activity / goal / sex change.

    Subscribed to by the nutrition context to trigger recalibration.
    """

    user_id: UUID
    weight_kg: Decimal | None
    height_cm: Decimal | None
    age: int | None
    sex: str | None
    goal: str | None
    activity_level: str | None
    at: datetime
