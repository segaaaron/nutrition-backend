"""Fasting use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.core.errors import ConflictError, NotFoundError
from app.core.event_bus import EventBus
from app.tracking.domain.fasting import (
    FastingCompleted,
    FastingMethod,
    FastingSession,
    FastingStarted,
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
