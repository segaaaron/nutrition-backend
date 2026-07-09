"""Vision ports (Protocols). Pure domain — no framework deps."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.vision.domain.entities import DetectedFoodItem, VisionJob


class VisionJobRepository(Protocol):
    async def save(self, job: VisionJob) -> None: ...
    async def get(self, job_id: UUID) -> VisionJob | None: ...
    async def mark_running(self, job_id: UUID) -> None: ...
    async def mark_completed(self, job_id: UUID, *, items: list[DetectedFoodItem]) -> None: ...
    async def mark_failed(self, job_id: UUID, *, error_code: str, detail: str) -> None: ...
    async def find_recent_completed_by_sha(
        self,
        *,
        image_sha256: str,
        ttl_days: int,
        current_prompt_sha256: str | None = None,
    ) -> tuple[list[DetectedFoodItem], str | None] | None:
        """Return `(items, original_prompt_sha256)` of a prior completed job
        with the same image within the TTL window, or None if no usable
        cache hit exists.

        Implementations MUST strip per-user matcher artefacts (matched_food_id,
        matched_name_norm, match_method) before returning to avoid PII
        leaks via cross-user dedup.
        """
        ...


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
        stage: str = "auto",
        plan_context: str | None = None,
        user_profile: dict | None = None,
    ) -> tuple[list[DetectedFoodItem], str]:  # returns (items, prompt_sha256)
        """stage — "auto": provider-internal cascade (legacy behaviour);
        "primary_only": cheap model, NO internal escalation (the pipeline
        decides after catalog grounding); "full_only": heavy model direct
        (pipeline-decided escalation)."""
        ...

    def current_prompt_sha256(self, *, locale: str, region: str) -> str:
        """SHA256 of the system prompt the provider would use right now.

        Used by the cache layer to invalidate entries when the prompt
        template changes. Pure function (no I/O).
        """
        ...

    async def is_food_image(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None = None,
    ) -> tuple[bool, str]:
        """Cheap pre-filter — returns ``(accept, reason)``.

        ``accept=True`` iff the image shows ready-to-consume food/drink
        providing >=20 kcal. ``reason`` is a short tag for telemetry/logging
        (e.g. ``"food"``, ``"supplement"``, ``"low_kcal"``, ``"non_food"``,
        ``"empty_plate"``, ``"uncertain"``, ``"parse_error_accept_default"``,
        ``"upstream_error_accept_default"``).

        Implementations should use the cheapest available vision model
        (gpt-4o-mini, ``detail="low"``, ~$0.0001/call). This is pure
        classification — no nutrition data is returned. Implementations
        MUST fail-open on upstream/parse errors so infrastructure flakes
        do not block legitimate uploads.
        """
        ...


class FoodMatcher(Protocol):
    async def match(
        self,
        *,
        name: str,
        amount_g: float,
        locale: str,
        user_id: UUID | None,
    ) -> tuple[UUID | None, str | None, str, float | None]:  # (food_id, name_norm, method, corrected_amount_g)
        ...


class JobNotifier(Protocol):
    async def notify(
        self,
        *,
        user_id: UUID,
        channel: str,
        # Any: SSE payload schema varies per channel (job status, coach hint, etc.).
        payload: dict[str, Any],
    ) -> None: ...
