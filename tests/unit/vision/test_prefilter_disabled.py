"""Pre-filter disabled via settings → provider.is_food_image MUST NOT be
called and the VisionJob is created exactly like the legacy path.
"""

from __future__ import annotations

import pytest

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
async def test_prefilter_flag_off_skips_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_FOOD_PREFILTER_ENABLED", "false")

    repo = FakeRepo()
    # Verdict would be REJECT — but the filter is disabled, so we must
    # never even ask the provider.
    provider = FakeProvider(verdict=(False, "supplement"))
    uc = SubmitPhoto(
        repo=repo,
        compressor=FakeCompressor(),
        bus=FakeBus(),
        enqueue=FakeEnqueue(),
        provider=provider,
    )

    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    job_id = await uc(
        user_id=make_user_id(),
        meal_time="lunch",
        raw_bytes=raw,
        mime="image/jpeg",
        idempotency_key="k-disabled-1",
    )

    assert job_id is not None
    assert len(repo.saved) == 1
    assert provider.prefilter_calls == []

    get_settings.cache_clear()
