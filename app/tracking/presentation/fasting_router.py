"""Fasting REST endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, Field

from app.core.event_bus import get_event_bus
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.tracking.application.fasting_uc import (
    GetActiveFasting,
    GetFastingHistory,
    StartFasting,
    StopFasting,
)
from app.tracking.infrastructure.fasting_repository import SqlFastingRepository

router = APIRouter(tags=["fasting"])


class StartFastingBody(BaseModel):
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),  # noqa: ARG001
) -> StartFastingOut:
    uc = StartFasting(repo=SqlFastingRepository(session), bus=get_event_bus())
    fs = await uc(user_id=current_user, method_h=body.method_h)
    return StartFastingOut(
        id=fs.id, method_h=fs.method_h, start_ts=fs.start_ts.isoformat(), target_s=fs.target_s,
    )


class StopFastingOut(BaseModel):
    id: UUID
    duration_s: int
    target_s: int
    achieved: bool


@router.post("/fasting/{session_id}/stop", response_model=StopFastingOut)
async def stop_fasting(
    session_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> StopFastingOut:
    uc = StopFasting(repo=SqlFastingRepository(session), bus=get_event_bus())
    fs = await uc(user_id=current_user, session_id=session_id)
    return StopFastingOut(
        id=fs.id, duration_s=fs.duration_s or 0, target_s=fs.target_s, achieved=fs.achieved,
    )


@router.get("/fasting/active")
async def active_fasting(current_user: CurrentUserDep, session: SessionDep) -> dict:
    uc = GetActiveFasting(repo=SqlFastingRepository(session))
    return {"active": await uc(user_id=current_user)}


@router.get("/fasting/history")
async def fasting_history(
    current_user: CurrentUserDep,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = 30,
) -> dict:
    uc = GetFastingHistory(repo=SqlFastingRepository(session))
    return await uc(user_id=current_user, cursor=cursor, limit=limit)
