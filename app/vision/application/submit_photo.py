"""SubmitPhoto use case — validates upload, compresses via pyvips, persists
VisionJob row, enqueues `vision_recognize_task`.

Rate limit (10/hour/user) is enforced in the router with Redis counters.
Max upload size: 8 MB raw, enforced before reading the body.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.core.metrics import VISION_PREFILTER_TOTAL
from app.imaging.domain.contracts import CompressionProfile, ImageCompressor
from app.imaging.domain.mime_sniff import assert_mime_matches
from app.vision.domain.entities import VisionJob
from app.vision.domain.events import VisionJobEnqueued
from app.vision.domain.ports import VisionJobRepository, VisionProvider

log = get_logger("vision.submit")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8MB
ALLOWED_MIME = ("image/jpeg", "image/png", "image/heic", "image/heif", "image/webp")

# Free-text portion-calibration note from the user ("plato familiar",
# "es individual"). The single biggest error source is portion size, and one
# short phrase from the user measurably improves the estimate. Capped + cleaned
# before it reaches the LLM prompt.
MAX_USER_CONTEXT_LEN = 160


def sanitize_user_context(text: str | None) -> str | None:
    """Clean an optional user note for safe injection into the vision prompt:
    strip control chars, collapse whitespace, cap length. Returns None when
    empty so downstream simply omits the calibration line."""
    if not text:
        return None
    cleaned = "".join(
        ch if (ch.isprintable() and ch not in "\r\n\t") else " " for ch in text
    )
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return None
    return cleaned[:MAX_USER_CONTEXT_LEN]


@dataclass(slots=True)
class SubmitPhoto:
    repo: VisionJobRepository
    compressor: ImageCompressor
    bus: EventBus
    enqueue: Any  # callable: async (task_name, **kwargs) -> job_id
    # Optional cheap pre-filter (gpt-4o-mini detail:low). When None or when
    # ``settings.vision_food_prefilter_enabled`` is False, the pre-filter step
    # is skipped — preserves legacy behaviour and keeps tests simple.
    provider: VisionProvider | None = None

    async def __call__(  # noqa: PLR0913 — keyword-only entrypoint; args are cohesive request fields (user, meal_time, bytes, mime, idempotency, locale, region).
        self,
        *,
        user_id: UUID,
        meal_time: Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"],
        raw_bytes: bytes,
        mime: str,
        idempotency_key: str | None,
        locale: str = "en",
        region: str = "us",
        user_context: str | None = None,
        persist: bool = True,
    ) -> UUID:
        if len(raw_bytes) == 0:
            raise ValidationError("empty_upload")
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise ValidationError(f"upload_too_large:{len(raw_bytes)}")
        if mime not in ALLOWED_MIME:
            raise ValidationError(f"unsupported_mime:{mime}")
        clean_context = sanitize_user_context(user_context)
        # OWASP ASVS V12 — verify declared MIME matches actual bytes
        # (anti-polyglot upload: PHP/SVG/EXE disguised as image).
        try:
            mime = assert_mime_matches(raw_bytes, mime)
        except ValueError as e:
            raise ValidationError(str(e)) from e

        compressed = await self.compressor.compress(
            raw_bytes,
            profile=CompressionProfile.MEAL_PHOTO,
        )
        sha = hashlib.sha256(compressed.bytes_).hexdigest()

        # --- Cheap food/no-food pre-filter (saves ~$0.005/rejected photo) ---
        if self.provider is not None and get_settings().vision_food_prefilter_enabled:
            accept, reason = await self.provider.is_food_image(
                image_bytes=compressed.bytes_,
                mime=f"image/{compressed.format}",
                user_id=user_id,
            )
            VISION_PREFILTER_TOTAL.labels(
                result="accept" if accept else "reject",
                reason=reason,
            ).inc()
            if not accept:
                log.info(
                    "vision.prefilter.rejected",
                    user_id=str(user_id),
                    reason=reason,
                    sha=sha[:8],
                )
                raise ValidationError(f"not_food_image:{reason}")

        now = datetime.now(UTC)

        job = VisionJob(
            id=uuid4(),
            user_id=user_id,
            meal_time=meal_time,
            status="queued",
            image_sha256=sha,
            image_bytes=len(compressed.bytes_),
            idempotency_key=idempotency_key,
            created_at=now,
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
            user_context=clean_context,
            persist=persist,
        )

        await self.bus.publish(
            VisionJobEnqueued(
                job_id=job.id,
                user_id=user_id,
                meal_time=meal_time,
                at=now,
            )
        )
        # PII: no item names — just count.
        log.info("vision.submit.queued", job_id=str(job.id), bytes=len(compressed.bytes_))
        return job.id
