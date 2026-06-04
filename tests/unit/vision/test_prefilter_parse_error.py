"""Pre-filter parse-error fail-open: malformed JSON from the upstream model
must NOT block the upload. Provider returns
(True, "parse_error_accept_default").
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.vision.application.submit_photo import SubmitPhoto
from app.vision.infrastructure import openai_vision as ov
from tests.unit.vision._prefilter_helpers import (
    FakeBus,
    FakeCompressor,
    FakeEnqueue,
    FakeRepo,
    make_user_id,
)


def _resp(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=180, completion_tokens=10),
    )


@pytest.fixture
def _no_cost_cap(monkeypatch: pytest.MonkeyPatch):
    async def _ok(**_kw):
        return None

    monkeypatch.setattr(ov, "pre_check", _ok)

    async def _rec(**_kw):
        return 0.0

    monkeypatch.setattr(ov, "record_usage", _rec)


@pytest.mark.asyncio
async def test_provider_returns_accept_on_malformed_json(
    _no_cost_cap,
) -> None:
    create = AsyncMock(return_value=_resp("{not-json"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        accept, reason = await provider.is_food_image(
            image_bytes=b"\x89PNG_FAKE_BYTES_",
            mime="image/webp",
            user_id=None,
        )
    assert accept is True
    assert reason == "parse_error_accept_default"


@pytest.mark.asyncio
async def test_provider_returns_accept_on_missing_keys(
    _no_cost_cap,
) -> None:
    # Well-formed JSON but missing the schema-required "accept" field.
    create = AsyncMock(return_value=_resp('{"reason": "food"}'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        accept, reason = await provider.is_food_image(
            image_bytes=b"\x89PNG_FAKE_BYTES_",
            mime="image/webp",
            user_id=None,
        )
    assert accept is True
    assert reason == "parse_error_accept_default"


@pytest.mark.asyncio
async def test_submit_photo_proceeds_on_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_FOOD_PREFILTER_ENABLED", "true")

    async def _ok(**_kw):
        return None

    monkeypatch.setattr(ov, "pre_check", _ok)

    async def _rec(**_kw):
        return 0.0

    monkeypatch.setattr(ov, "record_usage", _rec)

    create = AsyncMock(return_value=_resp("not-json-at-all"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    repo = FakeRepo()
    uc = SubmitPhoto(
        repo=repo,
        compressor=FakeCompressor(),
        bus=FakeBus(),
        enqueue=FakeEnqueue(),
        provider=ov.OpenAIVisionProvider(),
    )
    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    with patch.object(ov, "_get_client", return_value=client):
        job_id = await uc(
            user_id=make_user_id(),
            meal_time="lunch",
            raw_bytes=raw,
            mime="image/jpeg",
            idempotency_key="k-parse-1",
        )
    assert job_id is not None
    assert len(repo.saved) == 1
    get_settings.cache_clear()
