"""Fasting sub-domain: FastingSession entity, FastingMethod enum, FastingResult VO."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from uuid import UUID

from app.core.event_bus import DomainEvent


class FastingMethod(IntEnum):
    SIXTEEN = 16
    EIGHTEEN = 18
    TWENTY = 20

    @property
    def target_seconds(self) -> int:
        return int(self) * 3600


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

    @classmethod
    def start(cls, *, id_: UUID, user_id: UUID, method: FastingMethod) -> "FastingSession":
        return cls(
            id=id_, user_id=user_id, method_h=int(method),
            start_ts=datetime.now(timezone.utc),
            target_s=method.target_seconds,
        )

    def stop(self) -> None:
        if self.end_ts is not None:
            raise ValueError("fasting_already_stopped")
        now = datetime.now(timezone.utc)
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
