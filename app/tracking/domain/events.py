"""Tracking domain events.

`WeightLogged` is the canonical home for the event. The nutrition handler
already imports a duck-typed copy (`app.nutrition.event_handlers.WeightLogged`)
so this re-export becomes the source of truth — both classes are structurally
compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class WaterLogged(DomainEvent):
    user_id: UUID
    ml: int
    at: datetime


@dataclass(frozen=True, slots=True)
class WeightLogged(DomainEvent):
    user_id: UUID
    weight_kg: Decimal
    at: datetime


@dataclass(frozen=True, slots=True)
class FoodLogged(DomainEvent):
    """Stub — implemented in Sprint 5 alongside the Vision IA bounded context."""

    user_id: UUID
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"]
    kcal: int
    at: datetime
