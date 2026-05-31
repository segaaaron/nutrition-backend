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

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.errors import RateLimited, ValidationError
from app.core.event_bus import get_event_bus
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.imaging.infrastructure.vips_compressor import VipsImageCompressor
from app.vision.application.get_job_status import GetJobStatus
from app.vision.application.learn_user_correction import LearnUserCorrection
from app.vision.application.submit_photo import SubmitPhoto
from app.vision.infrastructure.repositories import SqlVisionJobRepository
from app.vision.presentation.schemas import (
    DetectedItemDto,
    EditDetectedItemRequest,
    JobStatusResponse,
    SubmitPhotoResponse,
)

router = APIRouter(tags=["vision"])

RATE_LIMIT_PER_HOUR = 10
_arq_pool: ArqRedis | None = None


async def _get_arq() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        from arq.connections import RedisSettings
        _arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _arq_pool


async def _enqueue(task_name: str, **kwargs) -> None:
    pool = await _get_arq()
    await pool.enqueue_job(task_name, **kwargs)


async def _check_rate_limit(user_id: UUID) -> None:
    r = get_redis()
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    key = f"rl:vision:{user_id}:{hour_bucket}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3700)
    n, _ = await pipe.execute()
    if int(n) > RATE_LIMIT_PER_HOUR:
        raise RateLimited("vision_hourly_cap", retry_after_s=3600)


@router.post(
    "/logs/food/photo",
    response_model=SubmitPhotoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_food_photo(
    current_user: CurrentUserDep,
    session: SessionDep,
    image: Annotated[UploadFile, File(description="meal photo, max 8MB")],
    meal_time: Annotated[Literal["breakfast", "lunch", "dinner", "snack"], Form()] = "lunch",
    locale: Annotated[str, Form()] = "en",
    region: Annotated[str, Form()] = "us",
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
    )
    job_id = await uc(
        user_id=current_user, meal_time=meal_time,
        raw_bytes=raw, mime=image.content_type or "image/jpeg",
        idempotency_key=idempotency_key,
        locale=locale, region=region,
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
    meal_time: Annotated[Literal["breakfast", "lunch", "dinner", "snack"], Form()] = "lunch",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmitPhotoResponse:
    return await submit_food_photo(
        current_user=current_user, session=session, image=image,
        meal_time=meal_time, locale="en", region="us",
        idempotency_key=idempotency_key,
    )


@router.get(
    "/logs/food/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> JobStatusResponse:
    uc = GetJobStatus(repo=SqlVisionJobRepository(session))
    job = await uc(job_id=job_id, user_id=current_user)
    return JobStatusResponse(
        job_id=job.id, status=job.status,
        items=[
            DetectedItemDto(
                name=i.name, estimated_amount_g=i.estimated_amount_g,
                kcal=i.kcal, protein_g=i.protein_g,
                carbs_g=i.carbs_g, fat_g=i.fat_g,
                confidence=i.confidence,
                matched_food_id=i.matched_food_id,
                match_method=i.match_method,
            )
            for i in job.detected_items
        ],
        error_code=job.error_code,
        created_at=job.created_at, completed_at=job.completed_at,
    )


@router.post("/logs/food/{food_log_id}/edit", status_code=status.HTTP_204_NO_CONTENT)
async def edit_food_log(
    food_log_id: UUID,
    body: EditDetectedItemRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    uc = LearnUserCorrection(session=session)
    await uc(
        user_id=current_user,
        detected_name=body.detected_name,
        corrected_food_id=body.corrected_food_id,
        corrected_amount_g=body.corrected_amount_g,
    )
