"""Voice + text food-log endpoints.

  POST /logs/food/text   {text, meal_time}
  POST /logs/food/voice  multipart (audio, meal_time)  — max 1MB, 60s
  POST /logs/food        manual {food_id|free_text_name, amount_g, meal_time}
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Header, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.errors import ValidationError
from app.core.event_bus import get_event_bus
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.vision.infrastructure.food_matcher import HybridFoodMatcher
from app.voice.application.log_text import LogFoodText
from app.voice.infrastructure.whisper_client import WhisperClient

router = APIRouter(tags=["voice"])

VOICE_MAX_BYTES = 1 * 1024 * 1024
VOICE_MAX_SECONDS = 60


class TextLogRequest(BaseModel):
    text: str
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    locale: str = "es"


class ManualLogRequest(BaseModel):
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"]
    food_id: UUID | None = None
    free_text_name: str | None = None
    amount_g: Decimal


class LogsCreatedResponse(BaseModel):
    food_log_ids: list[UUID]


@router.post("/logs/food/text", response_model=LogsCreatedResponse, status_code=status.HTTP_201_CREATED)
async def log_food_text(
    body: TextLogRequest,
    current_user: CurrentUserDep, session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> LogsCreatedResponse:
    uc = LogFoodText(
        session=session, matcher=HybridFoodMatcher(session), bus=get_event_bus(),
    )
    ids = await uc(
        user_id=current_user, meal_time=body.meal_time,
        raw_text=body.text, method="text", locale=body.locale,
        idempotency_key=idempotency_key,
    )
    return LogsCreatedResponse(food_log_ids=ids)


@router.post("/logs/food/voice", response_model=LogsCreatedResponse, status_code=status.HTTP_201_CREATED)
async def log_food_voice(
    current_user: CurrentUserDep, session: SessionDep,
    audio: Annotated[UploadFile, File(description="audio ≤1MB ≤60s")],
    meal_time: Annotated[Literal["breakfast", "lunch", "dinner", "snack"], Form()] = "lunch",
    locale: Annotated[str, Form()] = "es",
    duration_s: Annotated[float, Form()] = 30.0,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> LogsCreatedResponse:
    raw = await audio.read()
    if len(raw) > VOICE_MAX_BYTES:
        raise ValidationError("audio_too_large")
    if duration_s > VOICE_MAX_SECONDS:
        raise ValidationError(f"audio_too_long:{duration_s}s")

    transcript = await WhisperClient().transcribe(
        audio_bytes=raw, mime=audio.content_type or "audio/m4a",
        duration_s=duration_s, user_id=current_user, locale=locale,
    )
    uc = LogFoodText(
        session=session, matcher=HybridFoodMatcher(session), bus=get_event_bus(),
    )
    ids = await uc(
        user_id=current_user, meal_time=meal_time,
        raw_text=transcript, method="voice", locale=locale,
        idempotency_key=idempotency_key,
    )
    return LogsCreatedResponse(food_log_ids=ids)


@router.post("/logs/food", response_model=LogsCreatedResponse, status_code=status.HTTP_201_CREATED)
async def log_food_manual(
    body: ManualLogRequest,
    current_user: CurrentUserDep, session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> LogsCreatedResponse:
    if body.food_id is None and not body.free_text_name:
        raise ValidationError("food_id_or_free_text_required")

    kcal = protein = carbs = fat = 0
    if body.food_id is not None:
        row = (await session.execute(text("""
            SELECT COALESCE(kcal,0), COALESCE(protein_g,0),
                   COALESCE(carbs_g,0), COALESCE(fat_g,0)
              FROM foods WHERE id = :fid
        """), {"fid": str(body.food_id)})).first()
        if row:
            factor = float(body.amount_g) / 100.0
            kcal = int(float(row[0]) * factor)
            protein = int(float(row[1]) * factor)
            carbs = int(float(row[2]) * factor)
            fat = int(float(row[3]) * factor)

    flog_id = uuid4()
    await session.execute(text("""
        INSERT INTO food_logs (
            id, user_id, date, meal_time, food_id, free_text_name,
            amount_g, kcal, protein_g, carbs_g, fat_g,
            method, idempotency_key, created_at
        ) VALUES (
            :id, :uid, :d, :mt, :fid, :ftn,
            :ag, :kc, :pg, :cg, :fg,
            'manual', :idem, now()
        )
        ON CONFLICT (user_id, idempotency_key) DO NOTHING
    """), {
        "id": str(flog_id), "uid": str(current_user),
        "d": date.today(), "mt": body.meal_time,
        "fid": str(body.food_id) if body.food_id else None,
        "ftn": body.free_text_name,
        "ag": float(body.amount_g),
        "kc": kcal, "pg": protein, "cg": carbs, "fg": fat,
        "idem": idempotency_key,
    })
    return LogsCreatedResponse(food_log_ids=[flog_id])
