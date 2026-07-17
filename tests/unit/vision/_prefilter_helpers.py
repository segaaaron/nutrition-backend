"""Shared fixtures/fakes for the SubmitPhoto pre-filter tests.

These tests exercise the use case in isolation: they fake the repository,
the compressor, the event bus, and the enqueue callable so we can focus on
the pre-filter branch logic. The provider is the only collaborator that is
not faked at the protocol level — each test supplies its own ``provider``
double with a programmable ``is_food_image`` return.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from app.imaging.domain.value_objects import CompressedImage
from app.vision.domain.entities import DetectedFoodItem, VisionJob


class FakeCompressor:
    """Minimal ImageCompressor stub — returns a tiny WEBP-formatted blob."""

    async def compress(self, raw: bytes, *, profile: Any) -> CompressedImage:
        # 16 bytes of arbitrary "compressed" payload — deterministic SHA.
        return CompressedImage(
            bytes_=b"\x89PNG_FAKE_BYTES_",
            format="webp",
            width=400,
            height=400,
        )


@dataclass
class FakeRepo:
    saved: list[VisionJob] = field(default_factory=list)

    async def save(self, job: VisionJob) -> None:
        self.saved.append(job)

    async def get(self, job_id: UUID) -> VisionJob | None:
        for j in self.saved:
            if j.id == job_id:
                return j
        return None

    async def mark_running(self, job_id: UUID) -> None: ...
    async def mark_completed(
        self,
        job_id: UUID,
        *,
        items: list[DetectedFoodItem],
        prompt_sha256: str | None = None,
    ) -> None: ...
    async def mark_failed(self, job_id: UUID, *, error_code: str, detail: str) -> None: ...
    async def find_recent_completed_by_sha(
        self,
        *,
        image_sha256: str,
        ttl_days: int,
        current_prompt_sha256: str | None = None,
    ) -> tuple[list[DetectedFoodItem], str | None] | None:
        return None


class FakeBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class FakeEnqueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, task_name: str, **kwargs: Any) -> None:
        self.calls.append((task_name, kwargs))


class FakeProvider:
    """Programmable VisionProvider double. Records every is_food_image call."""

    def __init__(
        self,
        *,
        verdict: tuple[bool, str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.verdict = verdict or (True, "food")
        self.raises = raises
        self.prefilter_calls: list[dict[str, Any]] = []
        self.recognise_calls: list[dict[str, Any]] = []

    async def is_food_image(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None = None,
    ) -> tuple[bool, str]:
        self.prefilter_calls.append(
            {
                "mime": mime,
                "n_bytes": len(image_bytes),
                "user_id": user_id,
            }
        )
        if self.raises is not None:
            raise self.raises
        return self.verdict

    async def recognise(self, **kwargs: Any) -> tuple[list[DetectedFoodItem], str]:
        self.recognise_calls.append(kwargs)
        return [], "deadbeef"

    def current_prompt_sha256(self, *, locale: str, region: str) -> str:
        return "deadbeef"


def make_user_id() -> UUID:
    return uuid4()
