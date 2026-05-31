"""Async SQL repository for VisionJob aggregate."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.vision.domain.entities import DetectedFoodItem, VisionJob
from app.vision.infrastructure.models import VisionJobModel


def _items_to_jsonb(items: list[DetectedFoodItem]) -> list[dict]:
    return [
        {
            "name": i.name,
            "estimated_amount_g": float(i.estimated_amount_g),
            "kcal": i.kcal,
            "protein_g": i.protein_g,
            "carbs_g": i.carbs_g,
            "fat_g": i.fat_g,
            "confidence": i.confidence,
            "matched_food_id": str(i.matched_food_id) if i.matched_food_id else None,
            "matched_name_norm": i.matched_name_norm,
            "match_method": i.match_method,
        }
        for i in items
    ]


def _items_from_jsonb(raw: list[dict] | None) -> list[DetectedFoodItem]:
    if not raw:
        return []
    out: list[DetectedFoodItem] = []
    for d in raw:
        out.append(DetectedFoodItem(
            name=d["name"],
            estimated_amount_g=Decimal(str(d["estimated_amount_g"])),
            kcal=int(d["kcal"]), protein_g=int(d["protein_g"]),
            carbs_g=int(d["carbs_g"]), fat_g=int(d["fat_g"]),
            confidence=float(d["confidence"]),
            matched_food_id=UUID(d["matched_food_id"]) if d.get("matched_food_id") else None,
            matched_name_norm=d.get("matched_name_norm"),
            match_method=d.get("match_method"),
        ))
    return out


class SqlVisionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def save(self, job: VisionJob) -> None:
        now = datetime.now(timezone.utc)
        self.s.add(VisionJobModel(
            id=job.id, user_id=job.user_id, meal_time=job.meal_time,
            status=job.status, image_sha256=job.image_sha256,
            image_bytes=job.image_bytes, idempotency_key=job.idempotency_key,
            prompt_sha256=job.prompt_sha256, created_at=job.created_at or now,
        ))
        await self.s.flush()

    async def get(self, job_id: UUID) -> VisionJob | None:
        res = await self.s.execute(
            select(VisionJobModel).where(VisionJobModel.id == job_id)
        )
        m = res.scalar_one_or_none()
        if m is None:
            return None
        return VisionJob(
            id=m.id, user_id=m.user_id, meal_time=m.meal_time,  # type: ignore[arg-type]
            status=m.status,  # type: ignore[arg-type]
            image_sha256=m.image_sha256, image_bytes=m.image_bytes,
            idempotency_key=m.idempotency_key, prompt_sha256=m.prompt_sha256,
            detected_items=_items_from_jsonb(m.detected_items),  # type: ignore[arg-type]
            error_code=m.error_code, error_detail=m.error_detail,
            created_at=m.created_at, started_at=m.started_at,
            completed_at=m.completed_at,
        )

    async def mark_running(self, job_id: UUID) -> None:
        await self.s.execute(
            update(VisionJobModel)
            .where(VisionJobModel.id == job_id)
            .values(status="running", started_at=datetime.now(timezone.utc))
        )

    async def mark_completed(
        self, job_id: UUID, *, items: list[DetectedFoodItem]
    ) -> None:
        await self.s.execute(
            update(VisionJobModel)
            .where(VisionJobModel.id == job_id)
            .values(
                status="completed",
                detected_items=_items_to_jsonb(items),
                completed_at=datetime.now(timezone.utc),
            )
        )

    async def mark_failed(
        self, job_id: UUID, *, error_code: str, detail: str
    ) -> None:
        await self.s.execute(
            update(VisionJobModel)
            .where(VisionJobModel.id == job_id)
            .values(
                status="failed", error_code=error_code,
                error_detail=detail[:500],  # PII-redaction: cap detail length
                completed_at=datetime.now(timezone.utc),
            )
        )
