"""Pre-filter ACCEPT path: image classified as food → VisionJob created."""

from __future__ import annotations

import pytest

from app.core.metrics import VISION_PREFILTER_TOTAL
from app.vision.application.submit_photo import SubmitPhoto
from tests.unit.vision._prefilter_helpers import (
    FakeBus,
    FakeCompressor,
    FakeEnqueue,
    FakeProvider,
    FakeRepo,
    make_user_id,
)


@pytest.mark.asyncio
async def test_accept_creates_vision_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_FOOD_PREFILTER_ENABLED", "true")

    repo = FakeRepo()
    bus = FakeBus()
    enqueue = FakeEnqueue()
    provider = FakeProvider(verdict=(True, "food"))

    uc = SubmitPhoto(
        repo=repo,
        compressor=FakeCompressor(),
        bus=bus,
        enqueue=enqueue,
        provider=provider,
    )

    before = VISION_PREFILTER_TOTAL.labels(result="accept", reason="food")._value.get()

    user_id = make_user_id()
    # Minimal valid JPEG-looking bytes; assert_mime_matches accepts the
    # JPEG SOI marker.
    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    job_id = await uc(
        user_id=user_id,
        meal_time="lunch",
        raw_bytes=raw,
        mime="image/jpeg",
        idempotency_key="k-accept-1",
    )

    assert job_id is not None
    assert len(repo.saved) == 1
    assert len(provider.prefilter_calls) == 1
    assert provider.prefilter_calls[0]["user_id"] == user_id
    assert len(enqueue.calls) == 1
    after = VISION_PREFILTER_TOTAL.labels(result="accept", reason="food")._value.get()
    assert after == before + 1

    get_settings.cache_clear()
