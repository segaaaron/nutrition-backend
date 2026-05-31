"""SubmitPhoto use case — validates upload, compresses via pyvips, persists
VisionJob row, enqueues `vision_recognize_task`.

Rate limit (10/hour/user) is enforced in the router with Redis counters.
Max upload size: 8 MB raw, enforced before reading the body.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from app.core.errors import ValidationError
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.imaging.domain.contracts import CompressionProfile, ImageCompressor
from app.vision.domain.entities import VisionJob
from app.vision.domain.events import VisionJobEnqueued
from app.vision.domain.ports import VisionJobRepository

log = get_logger("vision.submit")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8MB
ALLOWED_MIME = ("image/jpeg", "image/png", "image/heic", "image/heif", "image/webp")


@dataclass(slots=True)
class SubmitPhoto:
    repo: VisionJobRepository
    compressor: ImageCompressor
    bus: EventBus
    enqueue: Any  # callable: async (task_name, **kwargs) -> job_id

    async def __call__(
        self,
        *,
        user_id: UUID,
        meal_time: Literal["breakfast", "lunch", "dinner", "snack"],
        raw_bytes: bytes,
        mime: str,
        idempotency_key: str | None,
        locale: str = "en",
        region: str = "us",
    ) -> UUID:
        if len(raw_bytes) == 0:
            raise ValidationError("empty_upload")
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise ValidationError(f"upload_too_large:{len(raw_bytes)}")
        if mime not in ALLOWED_MIME:
            raise ValidationError(f"unsupported_mime:{mime}")

        compressed = await self.compressor.compress(
            raw_bytes, profile=CompressionProfile.MEAL_PHOTO,
        )
        sha = hashlib.sha256(compressed.bytes_).hexdigest()
        now = datetime.now(timezone.utc)

        job = VisionJob(
            id=uuid4(), user_id=user_id, meal_time=meal_time,
            status="queued",
            image_sha256=sha, image_bytes=len(compressed.bytes_),
            idempotency_key=idempotency_key, created_at=now,
        )
        await self.repo.save(job)

        await self.enqueue(
            "vision_recognize_task",
            job_id=str(job.id),
            user_id=str(user_id),
            meal_time=meal_time,
            image_b64=__import__("base64").b64encode(compressed.bytes_).decode(),
            mime=f"image/{compressed.format}",
            locale=locale,
            region=region,
        )

        await self.bus.publish(VisionJobEnqueued(
            job_id=job.id, user_id=user_id, meal_time=meal_time, at=now,
        ))
        # PII: no item names — just count.
        log.info("vision.submit.queued", job_id=str(job.id), bytes=len(compressed.bytes_))
        return job.id
