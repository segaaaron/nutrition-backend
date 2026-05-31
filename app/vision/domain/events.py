"""Vision domain events. Consumed by tracking (food_logs), coach (cross-check)
and gamification (daily_goals)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class VisionJobEnqueued(DomainEvent):
    job_id: UUID
    user_id: UUID
    meal_time: str
    at: datetime


@dataclass(frozen=True, slots=True)
class VisionJobCompleted(DomainEvent):
    job_id: UUID
    user_id: UUID
    n_items: int
    total_kcal: int
    at: datetime


@dataclass(frozen=True, slots=True)
class VisionJobFailed(DomainEvent):
    job_id: UUID
    user_id: UUID
    error_code: str
    at: datetime


@dataclass(frozen=True, slots=True)
class FoodPhotoLogged(DomainEvent):
    """Emitted once per successful photo log (one event per photo, not per item).

    Coach subscribes to generate the 1-line cross-check hint (feature B).
    Gamification subscribes to update daily_goals[meal_time].
    """

    user_id: UUID
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"]
    kcal: int
    food_log_ids: tuple[UUID, ...]
    detected_names: tuple[str, ...]  # for coach hint — never logged
    at: datetime
