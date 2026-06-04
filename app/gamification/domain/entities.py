"""Gamification entities + VO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class StreakType(StrEnum):
    DAILY = "daily"
    FASTING = "fasting"
    PROTEIN = "protein"
    # Note: streak_type_enum currently only allows daily/fasting/protein.
    # Future extension (HYDRATION) requires an ALTER TYPE migration.


@dataclass(slots=True)
class Streak:
    user_id: UUID
    type: StreakType
    value: int
    last_day: date | None


@dataclass(slots=True)
class Achievement:
    user_id: UUID
    code: str
    unlocked_at: datetime


@dataclass(frozen=True, slots=True)
class UserLevel:
    """Level curve: level n requires `100 * n^1.5` total points (cumulative).

    Inverse: from total points P, level = floor((P/100) ** (1/1.5)).
    Reasoning: super-linear cost flattens early progression for new users
    (level 1 → 2 at 100 pts), while extending mid-game (level 10 → 11 at
    ~3162 pts) to keep long-term retention loops alive.
    """

    points: int
    level: int
    next_level_points: int

    @classmethod
    def from_points(cls, points: int) -> UserLevel:
        if points <= 0:
            return cls(points=0, level=0, next_level_points=100)
        level = int((points / 100.0) ** (1 / 1.5))
        next_pts = int(100 * ((level + 1) ** 1.5))
        return cls(points=points, level=level, next_level_points=next_pts)
