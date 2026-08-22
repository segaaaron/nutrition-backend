"""Fasting REST endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.errors import NotFoundError
from app.core.event_bus import get_event_bus
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.profile.infrastructure.repositories import SqlProfileRepository
from app.tracking.application.fasting_uc import (
    GetActiveFasting,
    GetFastingActiveState,
    GetFastingHistory,
    GetFastingLogs,
    GetFastingPreference,
    LogFastingWindow,
    StartFasting,
    StopFasting,
    UpsertFastingPreference,
)
from app.tracking.infrastructure.fasting_repository import SqlFastingRepository

router = APIRouter(tags=["fasting"])


class StartFastingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_h: int = Field(..., description="Fasting protocol — one of 16/18/20")


class StartFastingOut(BaseModel):
    id: UUID
    method_h: int
    start_ts: str
    target_s: int


@router.post("/fasting/start", status_code=status.HTTP_201_CREATED, response_model=StartFastingOut)
async def start_fasting(
    body: StartFastingBody,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> StartFastingOut:
    # NOTE: `Idempotency-Key` not supported. Concurrent start is guarded by the
    # active-fasting uniqueness invariant inside `StartFasting` use case.
    uc = StartFasting(repo=SqlFastingRepository(session), bus=get_event_bus())
    fs = await uc(user_id=current_user, method_h=body.method_h)
    return StartFastingOut(
        id=fs.id,
        method_h=fs.method_h,
        start_ts=fs.start_ts.isoformat(),
        target_s=fs.target_s,
    )


class StopFastingOut(BaseModel):
    id: UUID
    duration_s: int
    target_s: int
    achieved: bool


@router.post("/fasting/{session_id}/stop", response_model=StopFastingOut)
async def stop_fasting(
    session_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> StopFastingOut:
    # BOLA OK: StopFasting use case checks fs.user_id != user_id → NotFoundError.
    uc = StopFasting(repo=SqlFastingRepository(session), bus=get_event_bus())
    fs = await uc(user_id=current_user, session_id=session_id)
    return StopFastingOut(
        id=fs.id,
        duration_s=fs.duration_s or 0,
        target_s=fs.target_s,
        achieved=fs.achieved,
    )


@router.get("/fasting/active")
async def active_fasting(current_user: CurrentUserDep, session: SessionDep) -> dict:
    uc = GetActiveFasting(repo=SqlFastingRepository(session))
    return {"active": await uc(user_id=current_user)}


@router.get("/fasting/history")
async def fasting_history(
    current_user: CurrentUserDep,
    session: SessionDep,
    cursor: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    uc = GetFastingHistory(repo=SqlFastingRepository(session))
    return await uc(user_id=current_user, cursor=cursor, limit=limit)


# ── F1: Fasting preference ────────────────────────────────────────────────────

class FastingPreferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    protocol: str | None = None
    window_start_local: str | None = None
    time_zone: str | None = None
    reminders_enabled: bool
    updated_at: str | None = None  # UTC ISO-8601


class FastingPreferencePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    protocol: str | None = None
    window_start_local: str | None = None
    time_zone: str | None = None
    reminders_enabled: bool = False


@router.get("/me/fasting-preference", response_model=FastingPreferenceResponse)
async def get_fasting_preference(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> FastingPreferenceResponse:
    uc = GetFastingPreference(repo=SqlFastingRepository(session))
    pref = await uc(user_id=current_user)
    return FastingPreferenceResponse(
        enabled=pref.enabled,
        protocol=pref.protocol,
        window_start_local=pref.window_start_local,
        time_zone=pref.time_zone,
        reminders_enabled=pref.reminders_enabled,
        updated_at=pref.updated_at.isoformat() if pref.updated_at else None,
    )


@router.put("/me/fasting-preference", response_model=FastingPreferenceResponse)
async def put_fasting_preference(
    body: FastingPreferencePut,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> FastingPreferenceResponse:
    # Fetch medical conditions to enforce pregnancy/lactation gate
    profile_repo = SqlProfileRepository(session)
    profile = await profile_repo.get(current_user)
    conditions: list[str] = list(profile.medical_conditions) if profile and profile.medical_conditions else []

    uc = UpsertFastingPreference(repo=SqlFastingRepository(session))
    pref = await uc(
        user_id=current_user,
        enabled=body.enabled,
        protocol=body.protocol,
        window_start_local=body.window_start_local,
        time_zone=body.time_zone,
        reminders_enabled=body.reminders_enabled,
        medical_conditions=conditions,
    )
    await session.commit()
    return FastingPreferenceResponse(
        enabled=pref.enabled,
        protocol=pref.protocol,
        window_start_local=pref.window_start_local,
        time_zone=pref.time_zone,
        reminders_enabled=pref.reminders_enabled,
        updated_at=pref.updated_at.isoformat() if pref.updated_at else None,
    )


# ── F2: Fasting logs ──────────────────────────────────────────────────────────

class FastingLogBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime
    ended_at: AwareDatetime
    protocol: str
    planned_hours: int
    completed: bool
    break_reason: str | None = None


@router.post("/logs/fasting", status_code=status.HTTP_201_CREATED)
async def log_fasting_window(
    body: FastingLogBody,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    uc = LogFastingWindow(repo=SqlFastingRepository(session))
    fs = await uc(
        user_id=current_user,
        started_at=body.started_at,
        ended_at=body.ended_at,
        protocol=body.protocol,
        planned_hours=body.planned_hours,
        completed=body.completed,
        break_reason=body.break_reason,
    )
    await session.commit()
    return {
        "id": str(fs.id),
        "started_at": fs.start_ts.isoformat(),
        "ended_at": fs.end_ts.isoformat() if fs.end_ts else None,
        "protocol": fs.protocol,
        "planned_hours": fs.target_s // 3600,
        "actual_hours": round((fs.duration_s or 0) / 3600, 2),
        "completed": fs.achieved,
        "break_reason": fs.break_reason,
    }


@router.get("/logs/fasting")
async def get_fasting_logs(
    current_user: CurrentUserDep,
    session: SessionDep,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    uc = GetFastingLogs(repo=SqlFastingRepository(session))
    return await uc(
        user_id=current_user,
        from_date=from_,
        to_date=to,
        cursor=cursor,
        limit=limit,
    )


# ── F3: Active fasting state ──────────────────────────────────────────────────

@router.get("/logs/fasting/active")
async def get_fasting_active_state(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    uc = GetFastingActiveState(repo=SqlFastingRepository(session))
    return await uc(user_id=current_user)
