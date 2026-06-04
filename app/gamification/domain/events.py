"""Gamification domain events emitted by handlers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class DayCompleted(DomainEvent):
    user_id: UUID
    on_date: date
    at: datetime


@dataclass(frozen=True, slots=True)
class CelebrationTriggered(DomainEvent):
    user_id: UUID
    code: str  # 'streak_7' | 'streak_30' | 'day_perfect' | …
    at: datetime


@dataclass(frozen=True, slots=True)
class AchievementUnlocked(DomainEvent):
    user_id: UUID
    code: str
    points: int
    at: datetime


@dataclass(frozen=True, slots=True)
class StreakBroken(DomainEvent):
    user_id: UUID
    type: str
    prev_value: int
    at: datetime


@dataclass(frozen=True, slots=True)
class LevelUp(DomainEvent):
    user_id: UUID
    level: int
    at: datetime
