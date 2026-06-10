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

from datetime import datetime, timezone  # noqa: F401 — re-exported for tests
from typing import Annotated, Any, Literal
from uuid import UUID

from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, File, Form, Header, Response, UploadFile, status

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
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
    DetectedItemDto,
    EditDetectedItemRequest,
    JobStatusResponse,
    PlateGroupDto,
    SubmitPhotoResponse,
)

router = APIRouter(tags=["vision"])

_log = get_logger("vision.router")

_arq_pool: ArqRedis | None = None


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
    summary: str | None = None
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
            summary = explanation.summary
        except Exception:  # noqa: BLE001 — explanation is decorative; never break the poll (items must still reach the client)
            _log.warning("vision.plate_explainer_failed", job_id=str(job_id))
            groups, total_kcal, summary = [], None, None
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        items=[
            DetectedItemDto(
                name=i.name,
                estimated_amount_g=i.estimated_amount_g,
                kcal=i.kcal,
                protein_g=i.protein_g,
                carbs_g=i.carbs_g,
                fat_g=i.fat_g,
                confidence=i.confidence,
                food_group=i.food_group,
                matched_food_id=i.matched_food_id,
                match_method=i.match_method,
            )
            for i in job.detected_items
        ],
        groups=groups,
        total_kcal=total_kcal,
        summary=summary,
        error_code=job.error_code,
        created_at=job.created_at,
        completed_at=job.completed_at,
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
