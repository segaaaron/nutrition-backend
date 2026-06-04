"""Text food-log endpoints — backend NEVER receives audio.

Endpoints:
    POST /logs/food/text   {text, meal_time}
        Device STT transcript (iOS SFSpeechRecognizer / Android SpeechRecognizer)
        OR user-typed free text. Backend parses text only.
    POST /logs/food        {food_id|free_text_name, amount_g, meal_time}
        Manual structured entry.

Voice processing contract:
    - Mobile app records + transcribes locally on device.
    - App POSTs transcript (string) to /logs/food/text.
    - Backend stores no audio, runs no STT.
    - Whisper removed 2026-06-03 (see CLAUDE.md session log + app/voice/__init__.py).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.core.errors import ConflictError, ValidationError
from app.core.event_bus import get_event_bus
from app.core.idempotency import (
    IdempotencyConflict,
    cached_to_response,
    lookup_redis,
    remember_redis,
    require_idempotency_key,
)
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.vision.infrastructure.food_matcher import HybridFoodMatcher
from app.voice.application.log_text import LogFoodText

router = APIRouter(tags=["voice"])


class TextLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    locale: str = "es"


class ManualLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_time: Literal["breakfast", "lunch", "dinner", "snack"]
    food_id: UUID | None = None
    free_text_name: str | None = None
    amount_g: Decimal


class LogsCreatedResponse(BaseModel):
    food_log_ids: list[UUID]


@router.post(
    "/logs/food/text", response_model=LogsCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def log_food_text(
    body: TextLogRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    """Text food-log endpoint. ``Idempotency-Key`` (UUIDv4) REQUIRED.

    Replay within 24 h returns the cached 201 body verbatim — no second
    DB write. Body mismatch with same key -> 409. RFC: draft-ietf-httpapi-
    idempotency-key-06.
    """
    key = require_idempotency_key(idempotency_key)
    raw_body = await request.body()
    redis = get_redis()
    try:
        skey, cached = await lookup_redis(
            redis=redis,
            user_id=str(current_user),
            path=request.url.path,
            raw_key=key,
            body=raw_body,
        )
    except IdempotencyConflict as exc:
        raise ConflictError("idempotency_body_mismatch") from exc
    if cached is not None:
        return cached_to_response(cached)

    uc = LogFoodText(
        session=session,
        matcher=HybridFoodMatcher(session),
        bus=get_event_bus(),
    )
    ids = await uc(
        user_id=current_user,
        meal_time=body.meal_time,
        raw_text=body.text,
        method="text",
        locale=body.locale,
        idempotency_key=key,
    )
    payload = LogsCreatedResponse(food_log_ids=ids)
    await remember_redis(
        redis=redis,
        storage_key=skey,
        body=raw_body,
        response_body=payload.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    return Response(
        content=payload.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/logs/food", response_model=LogsCreatedResponse, status_code=status.HTTP_201_CREATED)
async def log_food_manual(
    body: ManualLogRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    """Manual structured food log. ``Idempotency-Key`` (UUIDv4) REQUIRED.

    Parity with ``POST /logs/food/text`` (Sprint 3 D12). Replay within 24 h
    returns the cached 201 verbatim — no second DB write. Same key + different
    body -> 409. SQL ``ON CONFLICT (user_id, idempotency_key)`` retained as
    defense-in-depth.
    """
    if body.food_id is None and not body.free_text_name:
        raise ValidationError("food_id_or_free_text_required")

    key = require_idempotency_key(idempotency_key)
    raw_body = await request.body()
    redis = get_redis()
    try:
        skey, cached = await lookup_redis(
            redis=redis,
            user_id=str(current_user),
            path=request.url.path,
            raw_key=key,
            body=raw_body,
        )
    except IdempotencyConflict as exc:
        raise ConflictError("idempotency_body_mismatch") from exc
    if cached is not None:
        return cached_to_response(cached)

    kcal = protein = carbs = fat = 0
    if body.food_id is not None:
        row = (
            await session.execute(
                text(
                    """
            SELECT COALESCE(kcal,0), COALESCE(protein_g,0),
                   COALESCE(carbs_g,0), COALESCE(fat_g,0)
              FROM foods WHERE id = :fid
        """
                ),
                {"fid": str(body.food_id)},
            )
        ).first()
        if row:
            # CLAUDE.md non-negotiable #2 — Decimal for nutrition macro math.
            # Scale per-100g foods by amount_g/100 with banker's rounding;
            # only cast to int at the storage boundary.
            from decimal import ROUND_HALF_EVEN

            factor = body.amount_g / Decimal("100")

            def _scale(v: object) -> int:
                return int(
                    (Decimal(str(v)) * factor).quantize(
                        Decimal("1"),
                        rounding=ROUND_HALF_EVEN,
                    )
                )

            kcal = _scale(row[0])
            protein = _scale(row[1])
            carbs = _scale(row[2])
            fat = _scale(row[3])

    flog_id = uuid4()
    await session.execute(
        text(
            """
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
    """
        ),
        {
            "id": str(flog_id),
            "uid": str(current_user),
            "d": date.today(),
            "mt": body.meal_time,
            "fid": str(body.food_id) if body.food_id else None,
            "ftn": body.free_text_name,
            "ag": body.amount_g,
            "kc": kcal,
            "pg": protein,
            "cg": carbs,
            "fg": fat,
            "idem": key,
        },
    )
    payload = LogsCreatedResponse(food_log_ids=[flog_id])
    await remember_redis(
        redis=redis,
        storage_key=skey,
        body=raw_body,
        response_body=payload.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    return Response(
        content=payload.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_201_CREATED,
    )
