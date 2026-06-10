"""Async SQL repository for VisionJob aggregate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.vision.domain.entities import DetectedFoodItem, FoodGroup, VisionJob
from app.vision.infrastructure.models import VisionJobModel

# Mirror of the FoodGroup vocabulary for JSONB hygiene: rows written by a
# future/rolled-back enum version must degrade to "other", never leak an
# out-of-vocab string typed as FoodGroup (explain_plate would silently drop
# it from groups while still counting its kcal in the total).
_VALID_FOOD_GROUPS: frozenset[str] = frozenset(
    {"vegetable", "fruit", "grain", "protein", "dairy", "fat", "sweet", "beverage", "other"}
)


def _coerce_food_group(raw: object) -> FoodGroup | None:
    if raw is None:
        return None
    return raw if raw in _VALID_FOOD_GROUPS else "other"  # type: ignore[return-value]


def _items_to_jsonb(items: list[DetectedFoodItem]) -> list[dict[str, Any]]:
    # Any: JSONB rows mix str/int/float/None; storage layer is schemaless.
    return [
        {
            "name": i.name,
            "estimated_amount_g": float(i.estimated_amount_g),
            "kcal": i.kcal,
            "protein_g": i.protein_g,
            "carbs_g": i.carbs_g,
            "fat_g": i.fat_g,
            "confidence": i.confidence,
            "food_group": i.food_group,
            "matched_food_id": str(i.matched_food_id) if i.matched_food_id else None,
            "matched_name_norm": i.matched_name_norm,
            "match_method": i.match_method,
        }
        for i in items
    ]


def _strip_personal_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove per-user personalization artifacts before returning to a
    different user via the SHA dedup cache.

    Cached `detected_items` JSONB rows are the LLM detection output (name +
    macros + confidence) which is image-bound and shareable. The matched
    food_id / matched_name_norm / match_method are produced by the
    per-user FoodMatcher (which considers user.personal_foods and
    user.correction history) — those MUST be recomputed for the new user.
    """
    out: list[dict[str, Any]] = []
    for raw in items:
        clean = dict(raw)
        clean.pop("matched_food_id", None)
        clean.pop("matched_name_norm", None)
        clean.pop("match_method", None)
        out.append(clean)
    return out


def _items_from_jsonb(raw: list[dict[str, Any]] | None) -> list[DetectedFoodItem]:
    if not raw:
        return []
    out: list[DetectedFoodItem] = []
    for d in raw:
        out.append(
            DetectedFoodItem(
                name=d["name"],
                estimated_amount_g=Decimal(str(d["estimated_amount_g"])),
                kcal=int(d["kcal"]),
                protein_g=int(d["protein_g"]),
                carbs_g=int(d["carbs_g"]),
                fat_g=int(d["fat_g"]),
                confidence=float(d["confidence"]),
                food_group=_coerce_food_group(d.get("food_group")),
                matched_food_id=UUID(d["matched_food_id"]) if d.get("matched_food_id") else None,
                matched_name_norm=d.get("matched_name_norm"),
                match_method=d.get("match_method"),
            )
        )
    return out


class SqlVisionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def save(self, job: VisionJob) -> None:
        now = datetime.now(UTC)
        self.s.add(
            VisionJobModel(
                id=job.id,
                user_id=job.user_id,
                meal_time=job.meal_time,
                status=job.status,
                image_sha256=job.image_sha256,
                image_bytes=job.image_bytes,
                idempotency_key=job.idempotency_key,
                prompt_sha256=job.prompt_sha256,
                created_at=job.created_at or now,
            )
        )
        await self.s.flush()

    async def get(self, job_id: UUID) -> VisionJob | None:
        res = await self.s.execute(select(VisionJobModel).where(VisionJobModel.id == job_id))
        m = res.scalar_one_or_none()
        if m is None:
            return None
        return VisionJob(
            id=m.id,
            user_id=m.user_id,
            meal_time=m.meal_time,  # type: ignore[arg-type]
            status=m.status,  # type: ignore[arg-type]
            image_sha256=m.image_sha256,
            image_bytes=m.image_bytes,
            idempotency_key=m.idempotency_key,
            prompt_sha256=m.prompt_sha256,
            detected_items=_items_from_jsonb(m.detected_items),  # type: ignore[arg-type]
            error_code=m.error_code,
            error_detail=m.error_detail,
            created_at=m.created_at,
            started_at=m.started_at,
            completed_at=m.completed_at,
        )

    async def mark_running(self, job_id: UUID) -> None:
        await self.s.execute(
            update(VisionJobModel)
            .where(VisionJobModel.id == job_id)
            .values(status="running", started_at=datetime.now(UTC))
        )

    async def mark_completed(self, job_id: UUID, *, items: list[DetectedFoodItem]) -> None:
        await self.s.execute(
            update(VisionJobModel)
            .where(VisionJobModel.id == job_id)
            .values(
                status="completed",
                detected_items=_items_to_jsonb(items),
                completed_at=datetime.now(UTC),
            )
        )

    async def mark_failed(self, job_id: UUID, *, error_code: str, detail: str) -> None:
        await self.s.execute(
            update(VisionJobModel)
            .where(VisionJobModel.id == job_id)
            .values(
                status="failed",
                error_code=error_code,
                error_detail=detail[:500],  # PII-redaction: cap detail length
                completed_at=datetime.now(UTC),
            )
        )

    async def find_recent_completed_by_sha(
        self,
        *,
        image_sha256: str,
        ttl_days: int,
        current_prompt_sha256: str | None = None,
    ) -> tuple[list[DetectedFoodItem], str | None] | None:
        """SHA256 dedup lookup. Returns `(items, original_prompt_sha256)` for
        the most recent completed job with the same compressed image within
        `ttl_days`, or `None` on miss.

        Safety nets:
        - CRITICAL-2: strips personal-matcher fields (`matched_food_id`,
          `matched_name_norm`, `match_method`) BEFORE returning, so a
          different user receives only the LLM detection (name + macros)
          and reruns matching against their own catalog/personal foods.
        - HIGH-1: when `current_prompt_sha256` is provided, the cache hit
          is only valid if the original row's prompt sha matches. This
          invalidates the dedup cache automatically on prompt template
          changes, preserving the audit contract.

        Backed by a partial index (see migration 0011) on
        `(image_sha256, created_at DESC) WHERE status='completed' AND
        detected_items IS NOT NULL` for sub-ms latency at scale.
        """
        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        stmt = (
            select(
                VisionJobModel.detected_items,
                VisionJobModel.prompt_sha256,
            )
            .where(
                VisionJobModel.image_sha256 == image_sha256,
                VisionJobModel.status == "completed",
                VisionJobModel.created_at >= cutoff,
                VisionJobModel.detected_items.isnot(None),
            )
            .order_by(VisionJobModel.created_at.desc())
            .limit(1)
        )
        if current_prompt_sha256 is not None:
            stmt = stmt.where(VisionJobModel.prompt_sha256 == current_prompt_sha256)
        res = await self.s.execute(stmt)
        row = res.first()
        if row is None:
            return None
        raw_items, original_prompt_sha = row
        if raw_items is None:
            return None
        stripped = _strip_personal_fields(list(raw_items))
        return _items_from_jsonb(stripped), original_prompt_sha
