"""Fasting sub-domain: FastingSession entity, FastingMethod enum, FastingResult VO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Literal
from uuid import UUID

from app.core.event_bus import DomainEvent

# Valid protocol strings (ISO-style "fast_eat" hours)
VALID_PROTOCOLS = frozenset({"14_10", "16_8", "18_6", "20_4"})

# Protocol → fasting hours
PROTOCOL_HOURS: dict[str, int] = {
    "14_10": 14,
    "16_8": 16,
    "18_6": 18,
    "20_4": 20,
}

FastingState = Literal["fasting", "eating", "inactive"]


class FastingMethod(IntEnum):
    FOURTEEN = 14
    SIXTEEN = 16
    EIGHTEEN = 18
    TWENTY = 20

    @property
    def target_seconds(self) -> int:
        return int(self) * 3600

    @property
    def protocol(self) -> str:
        return {14: "14_10", 16: "16_8", 18: "18_6", 20: "20_4"}[int(self)]

    @classmethod
    def from_protocol(cls, protocol: str) -> "FastingMethod":
        return cls(PROTOCOL_HOURS[protocol])


@dataclass(slots=True)
class FastingPreference:
    """User's fasting preference (persisted in user_fasting_preferences)."""

    user_id: UUID
    enabled: bool = False
    protocol: str | None = None      # "14_10" | "16_8" | "18_6" | "20_4"
    window_start_local: str | None = None  # "HH:MM" 24h
    time_zone: str | None = None     # IANA
    reminders_enabled: bool = False
    updated_at: datetime | None = None


@dataclass(slots=True)
class FastingSession:
    """Aggregate. Invariant: end_ts >= start_ts when end_ts is set;
    duration_s = end_ts - start_ts; achieved = duration_s >= target_s.
    A user may have at most one open session (end_ts IS NULL).
    """

    id: UUID
    user_id: UUID
    method_h: int
    start_ts: datetime
    target_s: int
    end_ts: datetime | None = None
    duration_s: int | None = None
    achieved: bool = False
    protocol: str | None = None
    break_reason: str | None = None

    @classmethod
    def start(cls, *, id_: UUID, user_id: UUID, method: FastingMethod) -> FastingSession:
        return cls(
            id=id_,
            user_id=user_id,
            method_h=int(method),
            start_ts=datetime.now(UTC),
            target_s=method.target_seconds,
        )

    def stop(self) -> None:
        if self.end_ts is not None:
            raise ValueError("fasting_already_stopped")
        now = datetime.now(UTC)
        self.end_ts = now
        self.duration_s = int((now - self.start_ts).total_seconds())
        self.achieved = self.duration_s >= self.target_s


@dataclass(frozen=True, slots=True)
class FastingResult:
    session_id: UUID
    method_h: int
    duration_s: int
    target_s: int
    achieved: bool


# --- Events ---


@dataclass(frozen=True, slots=True)
class FastingStarted(DomainEvent):
    session_id: UUID
    user_id: UUID
    method_h: int
    at: datetime


@dataclass(frozen=True, slots=True)
class FastingCompleted(DomainEvent):
    session_id: UUID
    user_id: UUID
    method_h: int
    duration_s: int
    achieved: bool
    at: datetime
