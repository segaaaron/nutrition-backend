"""Fasting use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.event_bus import EventBus
from app.tracking.domain.fasting import (
    VALID_PROTOCOLS,
    FastingCompleted,
    FastingMethod,
    FastingPreference,
    FastingSession,
    FastingStarted,
    PROTOCOL_HOURS,
)
from app.tracking.infrastructure.fasting_repository import (
    SqlFastingRepository,
    new_session_id,
)


@dataclass(slots=True)
class StartFasting:
    repo: SqlFastingRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID, method_h: int) -> FastingSession:
        if method_h not in (16, 18, 20):
            raise ConflictError(detail="invalid_method")
        active = await self.repo.active_for(user_id)
        if active is not None:
            raise ConflictError(detail="fasting_already_active", session_id=str(active.id))
        fs = FastingSession.start(
            id_=new_session_id(),
            user_id=user_id,
            method=FastingMethod(method_h),
        )
        await self.repo.insert(fs)
        await self.bus.publish(
            FastingStarted(
                session_id=fs.id,
                user_id=user_id,
                method_h=method_h,
                at=datetime.now(UTC),
            )
        )
        return fs


@dataclass(slots=True)
class StopFasting:
    repo: SqlFastingRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID, session_id: UUID) -> FastingSession:
        fs = await self.repo.get(session_id)
        if fs is None or fs.user_id != user_id:
            raise NotFoundError(detail="fasting_not_found")
        if fs.end_ts is not None:
            raise ConflictError(detail="fasting_already_stopped")
        fs.stop()
        await self.repo.finalize(fs)
        await self.bus.publish(
            FastingCompleted(
                session_id=fs.id,
                user_id=user_id,
                method_h=fs.method_h,
                duration_s=fs.duration_s or 0,
                achieved=fs.achieved,
                at=datetime.now(UTC),
            )
        )
        return fs


@dataclass(slots=True)
class GetActiveFasting:
    repo: SqlFastingRepository

    async def __call__(self, *, user_id: UUID) -> dict | None:
        fs = await self.repo.active_for(user_id)
        if fs is None:
            return None
        elapsed = int((datetime.now(UTC) - fs.start_ts).total_seconds())
        return {
            "id": str(fs.id),
            "method_h": fs.method_h,
            "start_ts": fs.start_ts.isoformat(),
            "elapsed_s": elapsed,
            "target_s": fs.target_s,
            "pct": round(min(100.0, elapsed / fs.target_s * 100.0), 1),
        }


@dataclass(slots=True)
class GetFastingHistory:
    repo: SqlFastingRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict:
        items, nxt = await self.repo.history(
            user_id=user_id,
            cursor=cursor,
            limit=min(limit, 100),
        )
        return {
            "items": [
                {
                    "id": str(i.id),
                    "method_h": i.method_h,
                    "start_ts": i.start_ts.isoformat(),
                    "end_ts": i.end_ts.isoformat() if i.end_ts else None,
                    "duration_s": i.duration_s,
                    "target_s": i.target_s,
                    "achieved": i.achieved,
                }
                for i in items
            ],
            "next_cursor": nxt,
        }


# ── F1: Fasting preference ────────────────────────────────────────────────────

@dataclass(slots=True)
class GetFastingPreference:
    repo: SqlFastingRepository

    async def __call__(self, *, user_id: UUID) -> FastingPreference:
        pref = await self.repo.get_preference(user_id)
        if pref is None:
            # Return empty-state preference — 200 not 404 (contract per F1)
            return FastingPreference(user_id=user_id)
        return pref


@dataclass(slots=True)
class UpsertFastingPreference:
    repo: SqlFastingRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        enabled: bool,
        protocol: str | None,
        window_start_local: str | None,
        time_zone: str | None,
        reminders_enabled: bool,
        medical_conditions: list[str],
    ) -> FastingPreference:
        if enabled and any(c in medical_conditions for c in ("pregnancy", "lactation")):
            raise BusinessRuleViolation("fasting:not_available")
        if protocol is not None and protocol not in VALID_PROTOCOLS:
            raise BusinessRuleViolation("fasting:invalid_protocol")
        pref = FastingPreference(
            user_id=user_id,
            enabled=enabled,
            protocol=protocol,
            window_start_local=window_start_local,
            time_zone=time_zone,
            reminders_enabled=reminders_enabled,
        )
        return await self.repo.upsert_preference(pref)


# ── F2: Log fasting window ────────────────────────────────────────────────────

@dataclass(slots=True)
class LogFastingWindow:
    repo: SqlFastingRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        started_at: datetime,
        ended_at: datetime,
        protocol: str,
        planned_hours: int,
        completed: bool,
        break_reason: str | None,
    ) -> FastingSession:
        if protocol not in VALID_PROTOCOLS:
            raise BusinessRuleViolation("fasting:invalid_protocol")
        now = datetime.now(UTC)
        if ended_at > now:
            raise BusinessRuleViolation("fasting:window_in_future")
        if started_at >= ended_at:
            raise BusinessRuleViolation("fasting:invalid_protocol")
        overlaps = await self.repo.has_overlapping(
            user_id=user_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        if overlaps:
            raise BusinessRuleViolation("fasting:overlapping_window")
        duration_s = int((ended_at - started_at).total_seconds())
        target_s = planned_hours * 3600
        fs = FastingSession(
            id=new_session_id(),
            user_id=user_id,
            method_h=PROTOCOL_HOURS[protocol],
            start_ts=started_at,
            end_ts=ended_at,
            duration_s=duration_s,
            target_s=target_s,
            achieved=completed,
            protocol=protocol,
            break_reason=break_reason,
        )
        await self.repo.insert_log(fs)
        return fs


@dataclass(slots=True)
class GetFastingLogs:
    repo: SqlFastingRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict:
        items, nxt = await self.repo.logs(
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            cursor=cursor,
            limit=min(limit, 100),
        )
        return {
            "items": [
                {
                    "id": str(i.id),
                    "started_at": i.start_ts.isoformat(),
                    "ended_at": i.end_ts.isoformat() if i.end_ts else None,
                    "protocol": i.protocol or _method_to_protocol(i.method_h),
                    "planned_hours": i.target_s // 3600,
                    "actual_hours": round((i.duration_s or 0) / 3600, 2),
                    "completed": i.achieved,
                    "break_reason": i.break_reason,
                }
                for i in items
            ],
            "next_cursor": nxt,
        }


def _method_to_protocol(method_h: int) -> str:
    return {14: "14_10", 16: "16_8", 18: "18_6", 20: "20_4"}.get(method_h, "16_8")


# ── F3: Active fasting state ──────────────────────────────────────────────────

@dataclass(slots=True)
class GetFastingActiveState:
    repo: SqlFastingRepository

    async def __call__(self, *, user_id: UUID) -> dict:
        """Return active fasting window state per F3 contract.

        state ∈ "fasting" | "eating" | "inactive"
        Never 404 — inactive is a valid state.
        """
        from datetime import timedelta
        fs = await self.repo.active_for(user_id)
        if fs is None:
            return {
                "state": "inactive",
                "window_started_at": None,
                "window_ends_at": None,
                "protocol": None,
            }
        now = datetime.now(UTC)
        ends_at = fs.start_ts + timedelta(seconds=fs.target_s)
        state = "fasting" if now < ends_at else "eating"
        proto = fs.protocol or _method_to_protocol(fs.method_h)
        return {
            "state": state,
            "window_started_at": fs.start_ts.isoformat(),
            "window_ends_at": ends_at.isoformat(),
            "protocol": proto,
        }
