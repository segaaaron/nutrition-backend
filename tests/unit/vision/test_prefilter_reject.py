"""Pre-filter REJECT path: supplement bottle → ValidationError, no job, no
escalation to the full recognise() cascade.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
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
async def test_reject_supplement_blocks_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_FOOD_PREFILTER_ENABLED", "true")

    repo = FakeRepo()
    bus = FakeBus()
    enqueue = FakeEnqueue()
    provider = FakeProvider(verdict=(False, "supplement"))
    uc = SubmitPhoto(
        repo=repo,
        compressor=FakeCompressor(),
        bus=bus,
        enqueue=enqueue,
        provider=provider,
    )

    before = VISION_PREFILTER_TOTAL.labels(
        result="reject",
        reason="supplement",
    )._value.get()

    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    with pytest.raises(ValidationError) as ei:
        await uc(
            user_id=make_user_id(),
            meal_time="lunch",
            raw_bytes=raw,
            mime="image/jpeg",
            idempotency_key="k-reject-1",
        )
    assert "not_food_image:supplement" in str(ei.value.detail)

    # No VisionJob persisted, no Arq enqueue, no event published,
    # and the expensive recognise() cascade was never invoked.
    assert repo.saved == []
    assert enqueue.calls == []
    assert bus.events == []
    assert provider.recognise_calls == []
    assert len(provider.prefilter_calls) == 1

    after = VISION_PREFILTER_TOTAL.labels(
        result="reject",
        reason="supplement",
    )._value.get()
    assert after == before + 1

    get_settings.cache_clear()
