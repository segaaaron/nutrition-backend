"""Unit — OpenAIVisionProvider cascade orchestration (mocks the SDK).

Asserts:
- High primary confidence => fallback NOT called.
- Low primary confidence => fallback called exactly once with fallback model.
- Empty primary items => fallback called.
- `max_tokens` cap is passed to the OpenAI client.
- Detail level "low" is forwarded for small images, "high" for large ones.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.vision.infrastructure import openai_vision as ov


def _png(w: int, h: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def _mk_response(items: list[dict[str, Any]]) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({"items": items})),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=180),
    )


@pytest.fixture
def _no_cost_cap(monkeypatch: pytest.MonkeyPatch):
    async def _ok(**_kw):
        return None

    monkeypatch.setattr(ov, "pre_check", _ok)

    async def _rec(**_kw):
        return 0.0

    monkeypatch.setattr(ov, "record_usage", _rec)


@pytest.fixture
def _disable_breaker(monkeypatch: pytest.MonkeyPatch):
    async def _call(fn):
        return await fn()

    monkeypatch.setattr(ov._breaker, "call", _call)


@pytest.fixture
def _settings(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OPENAI_VISION_MODEL_PRIMARY", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_VISION_MODEL_FALLBACK", "gpt-4o-2024-08-06")
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "true")
    monkeypatch.setenv("VISION_CONFIDENCE_THRESHOLD", "0.7")
    monkeypatch.setenv("VISION_MAX_OUTPUT_TOKENS", "400")
    monkeypatch.setenv("VISION_LOW_DETAIL_MAX_DIM", "500")
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_high_confidence_no_fallback(
    _no_cost_cap,
    _disable_breaker,
    _settings,
) -> None:
    high_items = [
        {
            "name": "avena",
            "estimated_amount_g": 60,
            "kcal": 230,
            "protein_g": 7,
            "carbs_g": 40,
            "fat_g": 4,
            "confidence": 0.92,
        },
        {
            "name": "platano",
            "estimated_amount_g": 120,
            "kcal": 105,
            "protein_g": 1,
            "carbs_g": 27,
            "fat_g": 0,
            "confidence": 0.88,
        },
    ]
    create = AsyncMock(return_value=_mk_response(high_items))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        items, _ = await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="latam",
        )
    assert create.await_count == 1
    assert create.await_args.kwargs["model"] == "gpt-4o-mini"
    assert create.await_args.kwargs["max_tokens"] == 400
    # detail forwarded inside the image_url payload
    user_content = create.await_args.kwargs["messages"][1]["content"]
    image_part = next(p for p in user_content if p["type"] == "image_url")
    assert image_part["image_url"]["detail"] == "high"
    assert len(items) == 2


@pytest.mark.asyncio
async def test_low_confidence_triggers_fallback(
    _no_cost_cap,
    _disable_breaker,
    _settings,
) -> None:
    low_items = [
        {
            "name": "sopa",
            "estimated_amount_g": 200,
            "kcal": 150,
            "protein_g": 6,
            "carbs_g": 20,
            "fat_g": 3,
            "confidence": 0.55,
        },
    ]
    rich_items = [
        {
            "name": "sopa de pollo",
            "estimated_amount_g": 250,
            "kcal": 180,
            "protein_g": 12,
            "carbs_g": 18,
            "fat_g": 5,
            "confidence": 0.93,
        },
        {
            "name": "fideos",
            "estimated_amount_g": 50,
            "kcal": 70,
            "protein_g": 2,
            "carbs_g": 14,
            "fat_g": 0,
            "confidence": 0.9,
        },
    ]
    create = AsyncMock(
        side_effect=[
            _mk_response(low_items),
            _mk_response(rich_items),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        items, _ = await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="latam",
        )
    assert create.await_count == 2
    assert create.await_args_list[0].kwargs["model"] == "gpt-4o-mini"
    assert create.await_args_list[1].kwargs["model"] == "gpt-4o-2024-08-06"
    # Returned items must be the fallback (richer) output.
    assert len(items) == 2
    assert items[0].name == "sopa de pollo"


@pytest.mark.asyncio
async def test_empty_primary_triggers_fallback(
    _no_cost_cap,
    _disable_breaker,
    _settings,
) -> None:
    rich_items = [
        {
            "name": "ensalada",
            "estimated_amount_g": 150,
            "kcal": 80,
            "protein_g": 3,
            "carbs_g": 10,
            "fat_g": 3,
            "confidence": 0.9,
        },
    ]
    create = AsyncMock(
        side_effect=[
            _mk_response([]),
            _mk_response(rich_items),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        items, _ = await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="us",
        )
    assert create.await_count == 2
    assert len(items) == 1


@pytest.mark.asyncio
async def test_small_image_uses_low_detail(
    _no_cost_cap,
    _disable_breaker,
    _settings,
) -> None:
    high_items = [
        {
            "name": "manzana",
            "estimated_amount_g": 150,
            "kcal": 80,
            "protein_g": 0,
            "carbs_g": 21,
            "fat_g": 0,
            "confidence": 0.95,
        },
    ]
    create = AsyncMock(return_value=_mk_response(high_items))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        await provider.recognise(
            image_bytes=_png(400, 400),
            mime="image/png",
            user_id=None,
            locale="es",
            region="us",
        )
    user_content = create.await_args.kwargs["messages"][1]["content"]
    image_part = next(p for p in user_content if p["type"] == "image_url")
    assert image_part["image_url"]["detail"] == "low"


@pytest.mark.asyncio
async def test_cascade_disabled_when_models_equal(
    _no_cost_cap,
    _disable_breaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OPENAI_VISION_MODEL_PRIMARY", "gpt-4o-2024-08-06")
    monkeypatch.setenv("OPENAI_VISION_MODEL_FALLBACK", "gpt-4o-2024-08-06")
    monkeypatch.setenv("VISION_CONFIDENCE_THRESHOLD", "0.7")
    monkeypatch.setenv("VISION_MAX_OUTPUT_TOKENS", "400")
    monkeypatch.setenv("VISION_LOW_DETAIL_MAX_DIM", "500")

    low_items = [
        {
            "name": "x",
            "estimated_amount_g": 10,
            "kcal": 5,
            "protein_g": 0,
            "carbs_g": 1,
            "fat_g": 0,
            "confidence": 0.1,
        },
    ]
    create = AsyncMock(return_value=_mk_response(low_items))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="us",
        )
    # Backward compat: even with low confidence, NO second call
    # because cascade is disabled (primary == fallback).
    assert create.await_count == 1
    get_settings.cache_clear()
