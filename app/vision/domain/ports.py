"""Vision ports (Protocols). Pure domain — no framework deps."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.vision.domain.entities import DetectedFoodItem, VisionJob


class VisionJobRepository(Protocol):
    async def save(self, job: VisionJob) -> None: ...
    async def get(self, job_id: UUID) -> VisionJob | None: ...
    async def mark_running(self, job_id: UUID) -> None: ...
    async def mark_completed(
        self, job_id: UUID, *, items: list[DetectedFoodItem]
    ) -> None: ...
    async def mark_failed(
        self, job_id: UUID, *, error_code: str, detail: str
    ) -> None: ...


class VisionProvider(Protocol):
    """The OpenAI vision adapter — returns raw detected items (unmatched)."""

    async def recognise(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None,
        locale: str,
        region: str,
    ) -> tuple[list[DetectedFoodItem], str]:  # returns (items, prompt_sha256)
        ...


class FoodMatcher(Protocol):
    async def match(
        self,
        *,
        name: str,
        amount_g: float,
        locale: str,
        user_id: UUID | None,
    ) -> tuple[UUID | None, str | None, str]:  # (food_id, name_norm, method)
        ...


class JobNotifier(Protocol):
    async def notify(
        self, *, user_id: UUID, channel: str, payload: dict
    ) -> None: ...
