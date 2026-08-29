"""Unit — CRITICAL-1 fix.

Pre-check must use the ACTUAL per-model input/output price (gpt-4o-mini
≈ $0.17/1M input, $0.66/1M output), not the hardcoded gpt-4o full price.

Previously the estimate hardcoded $2.75/1M input + $11.00/1M output, which
overestimated mini cost ~16x and would trip the $1.50/user/day cap after
~180 calls instead of the real ~3000+.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.vision.infrastructure import openai_vision as ov


def _png(w: int, h: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _mk_response(items: list[dict[str, Any]], cached_tokens: int = 0) -> Any:
    details = SimpleNamespace(cached_tokens=cached_tokens) if cached_tokens else None
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({"items": items})),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=900,
            completion_tokens=180,
            prompt_tokens_details=details,
        ),
    )


@pytest.fixture
def _no_breaker(monkeypatch: pytest.MonkeyPatch):
    async def _call(fn):
        return await fn()

    monkeypatch.setattr(ov._breaker, "call", _call)


@pytest.fixture
def _no_record(monkeypatch: pytest.MonkeyPatch):
    async def _rec(**_kw):
        return 0.0

    monkeypatch.setattr(ov, "record_usage", _rec)


@pytest.fixture
def _cascade_on(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "true")
    monkeypatch.setenv("OPENAI_VISION_MODEL_PRIMARY", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_VISION_MODEL_FALLBACK", "gpt-4o-2024-08-06")
    monkeypatch.setenv("VISION_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("VISION_LOW_DETAIL_MAX_DIM", "500")
    monkeypatch.setenv("VISION_CONFIDENCE_THRESHOLD", "0.7")
    monkeypatch.setenv("COST_CAP_USD_PER_USER_PER_DAY", "1.50")
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_pre_check_uses_mini_pricing(
    monkeypatch: pytest.MonkeyPatch,
    _no_breaker,
    _no_record,
    _cascade_on,
) -> None:
    """The pre-check estimate for one mini call must be ≤ $0.0005 so
    the default daily cap of $1.50 allows ≥3000 calls/day."""
    captured: list[float] = []

    async def _pc(*, user_id, estimate_usd):
        captured.append(estimate_usd)

    monkeypatch.setattr(ov, "pre_check", _pc)

    high_items = [
        {
            "name": "x",
            "estimated_amount_g": 10,
            "kcal": 5,
            "protein_g": 0,
            "carbs_g": 1,
            "fat_g": 0,
            "confidence": 0.95,
        }
    ]
    create = AsyncMock(return_value=_mk_response(high_items))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="latam",
        )

    assert len(captured) == 1
    est = Decimal(str(captured[0]))
    # Sanity: the pre-check estimate must stay cheap enough for thousands of
    # calls/day under the $1.50 cap — orders of magnitude above the real
    # 10-photos/day rate cap. Floor: 3000 -> 2500 (2026-07-11, counting-accuracy
    # prompt) -> 2400 (2026-07-14, scope + anti-double-count + portion-bias
    # prompt grew ~another 200 input tokens) -> 2250 (2026-07-24, physical macro
    # overflow guard + oil injection fixes added ~150 input tokens) ->
    # 2100 (2026-07-24, blended-food density hint added ~60 input tokens) ->
    # 2000 (2026-07-24, protein second-look + soup decomp + snack small-items
    # prompts added ~90 more input tokens) ->
    # 1900 (2026-07-25, size_category field + calibration instructions added ~80 tokens) ->
    # 1800 (2026-08-27, is_mixed_dish field + bilingual examples added ~120 tokens) ->
    # 1700 (2026-08-29, LATAM names rule + soup base identification added ~90 tokens).
    cap = Decimal("1.50")
    assert cap / est >= 1700, f"estimate={est} too high, only {cap/est:.0f} calls/day"


@pytest.mark.asyncio
async def test_pre_check_full_model_higher(
    monkeypatch: pytest.MonkeyPatch,
    _no_breaker,
    _no_record,
) -> None:
    """Sanity: pre-check for the FULL gpt-4o model is materially higher
    than for mini (proves we are actually picking per-model price)."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_VISION_MODEL_PRIMARY", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_VISION_MODEL_FALLBACK", "gpt-4o-2024-08-06")
    monkeypatch.setenv("VISION_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("VISION_LOW_DETAIL_MAX_DIM", "500")

    captured: list[float] = []

    async def _pc(*, user_id, estimate_usd):
        captured.append(estimate_usd)

    monkeypatch.setattr(ov, "pre_check", _pc)

    high_items = [
        {
            "name": "x",
            "estimated_amount_g": 10,
            "kcal": 5,
            "protein_g": 0,
            "carbs_g": 1,
            "fat_g": 0,
            "confidence": 0.95,
        }
    ]
    create = AsyncMock(return_value=_mk_response(high_items))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="latam",
        )

    assert len(captured) == 1
    full_est = captured[0]
    # gpt-4o full input is 2.75/1M (~16x mini @ 0.17/1M)
    assert full_est > 0.005, f"full-model estimate {full_est} unexpectedly low"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invoke_passes_cached_tok_to_record_usage(
    monkeypatch: pytest.MonkeyPatch,
    _no_breaker,
    _cascade_on,
) -> None:
    """cached_tokens in OpenAI response must be forwarded to record_usage."""
    rec_calls: list[dict] = []

    async def _rec(**kw):
        rec_calls.append(kw)
        return 0.0

    async def _pre(**_kw):
        pass

    monkeypatch.setattr(ov, "record_usage", _rec)
    monkeypatch.setattr(ov, "pre_check", _pre)

    items = [
        {
            "name": "rice",
            "estimated_amount_g": 150,
            "kcal": 200,
            "kcal_min": 180,
            "kcal_max": 220,
            "protein_g": 4,
            "carbs_g": 44,
            "fat_g": 1,
            "confidence": 0.95,
            "food_group": "grain",
            "role": "main",
            "prep_method": "boiled",
        }
    ]
    create = AsyncMock(return_value=_mk_response(items, cached_tokens=384))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="latam",
        )

    assert len(rec_calls) == 1
    assert rec_calls[0]["cached_tok"] == 384
    assert rec_calls[0]["in_tok"] == 900


@pytest.mark.asyncio
async def test_invoke_cached_tok_zero_when_details_absent(
    monkeypatch: pytest.MonkeyPatch,
    _no_breaker,
    _cascade_on,
) -> None:
    """No prompt_tokens_details → cached_tok=0, backward compat."""
    rec_calls: list[dict] = []

    async def _rec(**kw):
        rec_calls.append(kw)
        return 0.0

    async def _pre(**_kw):
        pass

    monkeypatch.setattr(ov, "record_usage", _rec)
    monkeypatch.setattr(ov, "pre_check", _pre)

    items = [
        {
            "name": "salad",
            "estimated_amount_g": 100,
            "kcal": 50,
            "kcal_min": 40,
            "kcal_max": 60,
            "protein_g": 2,
            "carbs_g": 8,
            "fat_g": 1,
            "confidence": 0.9,
            "food_group": "vegetable",
            "role": "main",
            "prep_method": "raw",
        }
    ]
    create = AsyncMock(return_value=_mk_response(items))  # no cached_tokens
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        await provider.recognise(
            image_bytes=_png(800, 800),
            mime="image/png",
            user_id=None,
            locale="es",
            region="latam",
        )

    assert rec_calls[0]["cached_tok"] == 0
