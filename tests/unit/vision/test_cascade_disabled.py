"""Unit — HIGH-4 fix: with `VISION_CASCADE_ENABLED=false` the pipeline must
call ONLY the fallback model (gpt-4o full) and never the mini primary.
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
def _no_breaker(monkeypatch: pytest.MonkeyPatch):
    async def _call(fn):
        return await fn()

    monkeypatch.setattr(ov._breaker, "call", _call)


@pytest.mark.asyncio
async def test_cascade_disabled_uses_fallback_only(
    monkeypatch: pytest.MonkeyPatch,
    _no_cost_cap,
    _no_breaker,
) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_VISION_MODEL_PRIMARY", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_VISION_MODEL_FALLBACK", "gpt-4o-2024-08-06")
    monkeypatch.setenv("VISION_CONFIDENCE_THRESHOLD", "0.7")
    monkeypatch.setenv("VISION_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("VISION_LOW_DETAIL_MAX_DIM", "500")

    low_items = [
        {
            "name": "x",
            "estimated_amount_g": 10,
            "kcal": 5,
            "protein_g": 0,
            "carbs_g": 1,
            "fat_g": 0,
            "confidence": 0.05,
        }
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
            region="latam",
        )

    # Exactly one call — straight to the fallback model. Cascade off
    # means: no mini call, no second escalation.
    assert create.await_count == 1
    assert create.await_args.kwargs["model"] == "gpt-4o-2024-08-06"
    get_settings.cache_clear()
