"""Vision router — photo upload, job status, user correction.

Endpoints:
  POST /logs/food/photo          (multipart, 8MB max, Idempotency-Key)
  GET  /logs/food/jobs/{jobId}   (poll)
  POST /logs/food/{id}/edit      (user correction → personal learning)
  POST /ai/recognize             (deprecated alias)

Rate limit: 10/hour/user via Redis counter (bucket key
`rl:vision:{uid}:{hour}`). Idempotency-Key is mandatory on POST photo and
short-circuits replay attacks.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone  # noqa: F401 — re-exported for tests
from typing import Annotated, Any, Literal
from uuid import UUID

from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, File, Form, Header, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
from app.imaging.infrastructure.vips_compressor import VipsImageCompressor
from app.shared.i18n.fastapi_dep import LocaleDep
from app.vision.application.get_job_status import GetJobStatus
from app.vision.application.learn_user_correction import LearnUserCorrection
from app.vision.application.submit_photo import SubmitPhoto
from app.vision.domain.plate_explainer import explain_plate
from app.vision.infrastructure.openai_vision import OpenAIVisionProvider
from app.vision.infrastructure.repositories import SqlVisionJobRepository
from app.vision.presentation.schemas import (
    BBoxDto,
    DetectedItemDto,
    EditDetectedItemRequest,
    JobStatusResponse,
    PlateGroupDto,
    SubmitPhotoResponse,
)

router = APIRouter(tags=["vision"])

_log = get_logger("vision.router")

_arq_pool: ArqRedis | None = None

_SSE_TIMEOUT = 120  # seconds before the stream closes with a timeout event
_SSE_HEARTBEAT = 15  # seconds between heartbeat events while job is pending


async def _pubsub_next(pubsub) -> dict:  # type: ignore[type-arg]
    """Block until the next real pubsub message arrives (non-subscribe type)."""
    while True:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if msg is not None:
            return msg


async def _get_arq() -> ArqRedis:
    global _arq_pool  # noqa: PLW0603 — module-level singleton (lazy init of arq pool); reset only in tests
    if _arq_pool is None:
        from arq.connections import RedisSettings

        _arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _arq_pool


async def _enqueue(task_name: str, **kwargs: Any) -> None:
    # Any: arq enqueue_job accepts arbitrary task-specific kwargs (job_id, user_id, bytes, ...).
    pool = await _get_arq()
    await pool.enqueue_job(task_name, **kwargs)


async def _check_rate_limit(user_id: UUID) -> None:
    """Thin shim — concrete logic lives in
    ``app.vision.presentation.rate_limit`` for testability."""
    from app.vision.presentation.rate_limit import check_photo_upload_rate_limit

    await check_photo_upload_rate_limit(user_id)


@router.post(
    "/logs/food/photo",
    response_model=SubmitPhotoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_food_photo(  # noqa: PLR0913 — FastAPI endpoint signature: deps + form/header fields are cohesive request inputs, not refactorable into a dataclass without losing OpenAPI schema.
    current_user: CurrentUserDep,
    session: SessionDep,
    image: Annotated[UploadFile, File(description="meal photo, max 8MB")],
    meal_time: Annotated[Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"], Form()] = "lunch",
    locale: Annotated[str, Form()] = "en",
    region: Annotated[str, Form()] = "us",
    note: Annotated[
        str | None,
        Form(description="optional portion cue, e.g. 'plato familiar' / 'es individual'"),
    ] = None,
    persist: Annotated[bool, Form(description="false = analyze only, do not write to food_logs")] = True,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmitPhotoResponse:
    if not idempotency_key:
        raise ValidationError("idempotency_key_required")
    await _check_rate_limit(current_user)

    raw = await image.read()
    uc = SubmitPhoto(
        repo=SqlVisionJobRepository(session),
        compressor=VipsImageCompressor(),
        bus=get_event_bus(),
        enqueue=_enqueue,
        provider=OpenAIVisionProvider(),
    )
    job_id = await uc(
        user_id=current_user,
        meal_time=meal_time,
        raw_bytes=raw,
        mime=image.content_type or "image/jpeg",
        idempotency_key=idempotency_key,
        locale=locale,
        region=region,
        user_context=note,
        persist=persist,
    )
    return SubmitPhotoResponse(job_id=job_id)


@router.post(
    "/ai/recognize",
    response_model=SubmitPhotoResponse,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
    summary="Deprecated alias — use POST /logs/food/photo",
)
async def ai_recognize_alias(
    current_user: CurrentUserDep,
    session: SessionDep,
    image: Annotated[UploadFile, File()],
    meal_time: Annotated[Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"], Form()] = "lunch",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmitPhotoResponse:
    return await submit_food_photo(
        current_user=current_user,
        session=session,
        image=image,
        meal_time=meal_time,
        locale="en",
        region="us",
        idempotency_key=idempotency_key,
    )


@router.get(
    "/logs/food/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    locale: LocaleDep,
) -> JobStatusResponse:
    # BOLA OK: GetJobStatus use case checks job.user_id != user_id → raises Forbidden.
    uc = GetJobStatus(repo=SqlVisionJobRepository(session))
    job = await uc(job_id=job_id, user_id=current_user)
    # Plate explanation: deterministic + localized, built at read time from
    # the persisted items (no extra AI call, no schema migration).
    groups: list[PlateGroupDto] = []
    total_kcal: int | None = None
    if job.status == "completed":
        try:
            explanation = explain_plate(job.detected_items, locale=locale)
            groups = [
                PlateGroupDto(
                    group=g.group,
                    label=g.label,
                    item_names=[i.name for i in g.items],
                    total_kcal=g.total_kcal,
                )
                for g in explanation.groups
            ]
            total_kcal = explanation.total_kcal
        except Exception:  # noqa: BLE001 — explanation is decorative; never break the poll (items must still reach the client)
            _log.warning("vision.plate_explainer_failed", job_id=str(job_id))
            groups, total_kcal = [], None

    # Macro totals — computed from items directly so they're available even
    # when the plate explainer fails.
    total_protein_g: int | None = None
    total_carbs_g: int | None = None
    total_fat_g: int | None = None
    total_fiber_g: int | None = None
    total_sugar_g: int | None = None
    if job.detected_items:
        total_protein_g = sum(i.protein_g for i in job.detected_items)
        total_carbs_g = sum(i.carbs_g for i in job.detected_items)
        total_fat_g = sum(i.fat_g for i in job.detected_items)
        total_fiber_g = sum(i.fiber_g for i in job.detected_items)
        total_sugar_g = sum(i.sugar_g for i in job.detected_items)

    # % of daily kcal goal — single cheap query, fail-silently so a missing
    # nutritional_goals row never breaks the poll response.
    pct_daily_kcal: float | None = None
    if total_kcal is not None and total_kcal > 0:
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT kcal_min, kcal_max FROM nutritional_goals "
                        "WHERE user_id = :uid AND valid_to IS NULL LIMIT 1"
                    ),
                    {"uid": str(current_user)},
                )
            ).first()
            if row and row[0] and row[1]:
                kcal_target = (int(row[0]) + int(row[1])) // 2
                if kcal_target > 0:
                    pct_daily_kcal = round(total_kcal / kcal_target * 100, 1)
        except Exception:  # noqa: BLE001 — decorative field; never break the poll
            _log.warning("vision.pct_daily_kcal.query_failed", job_id=str(job_id))

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        items=[
            DetectedItemDto(
                name=i.name,
                count=i.count,
                estimated_amount_g=i.estimated_amount_g,
                kcal=i.kcal,
                protein_g=i.protein_g,
                carbs_g=i.carbs_g,
                fat_g=i.fat_g,
                fiber_g=i.fiber_g,
                sugar_g=i.sugar_g,
                confidence=i.confidence,
                food_group=i.food_group,
                role=i.role,
                prep_method=i.prep_method,
                inferred=i.inferred,
                matched_food_id=i.matched_food_id,
                match_method=i.match_method,
                bbox=BBoxDto(x=i.bbox[0], y=i.bbox[1], w=i.bbox[2], h=i.bbox[3])
                if i.bbox
                else None,
            )
            for i in job.detected_items
        ],
        groups=groups,
        total_kcal=total_kcal,
        total_protein_g=total_protein_g,
        total_carbs_g=total_carbs_g,
        total_fat_g=total_fat_g,
        total_fiber_g=total_fiber_g,
        total_sugar_g=total_sugar_g,
        pct_daily_kcal=pct_daily_kcal,
        error_code=job.error_code,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get(
    "/logs/food/jobs/{job_id}/stream",
    summary="Stream vision job result via SSE (replaces polling)",
    response_class=StreamingResponse,
)
async def stream_job_status(
    job_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> StreamingResponse:
    """Server-Sent Events stream for a vision job.

    Events:
      heartbeat     — emitted every 15 s while the job is still pending
      vision_update — emitted when the job reaches a terminal status; connection closes
      timeout       — emitted after 120 s with no terminal event; client should poll
      error         — emitted when the Redis pubsub subscription fails; client should poll

    The StreamingResponse has Content-Type: text/event-stream, which causes
    ResponseEnvelopeMiddleware to skip wrapping automatically (non-JSON content type).
    """
    uc = GetJobStatus(repo=SqlVisionJobRepository(session))
    job = await uc(job_id=job_id, user_id=current_user)

    async def _generate() -> AsyncGenerator[str, None]:
        if job.status in ("completed", "failed", "cancelled"):
            payload = json.dumps(
                {"job_id": str(job.id), "status": job.status, "n_items": len(job.detected_items)},
                default=str,
            )
            yield f"event: vision_update\ndata: {payload}\n\n"
            return

        redis = get_redis()
        pubsub = redis.pubsub()
        channel = f"user:{current_user}:vision"
        try:
            await pubsub.subscribe(channel)
        except Exception:  # noqa: BLE001 — OK4: Redis unavailable; client degrades to polling
            yield 'event: error\ndata: {"code":"stream_unavailable"}\n\n'
            return

        deadline = time.monotonic() + _SSE_TIMEOUT
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                wait = min(remaining, float(_SSE_HEARTBEAT))
                try:
                    msg = await asyncio.wait_for(_pubsub_next(pubsub), timeout=wait)
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue

                try:
                    data = json.loads(msg["data"])
                except Exception:  # noqa: BLE001 — OK4: malformed pubsub payload; skip and keep listening
                    continue

                if str(data.get("job_id")) != str(job_id):
                    continue

                yield f"event: vision_update\ndata: {json.dumps(data, default=str)}\n\n"
                if data.get("status") in ("completed", "failed", "cancelled"):
                    return

            yield "event: timeout\ndata: {}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001 — OK7: cleanup; ignore close errors
                pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/logs/food/{food_log_id}/edit",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def edit_food_log(
    food_log_id: UUID,
    body: EditDetectedItemRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    # BOLA: verify the food_log belongs to current_user before applying correction.
    await assert_owns(session, table="food_logs", resource_id=food_log_id, user_id=current_user)
    uc = LearnUserCorrection(session=session)
    await uc(
        user_id=current_user,
        detected_name=body.detected_name,
        corrected_food_id=body.corrected_food_id,
        corrected_amount_g=body.corrected_amount_g,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
