"""Unit — HIGH-3 fix: truncated/malformed JSON from the model must return
empty items (NOT raise) so the cascade decision logic can escalate to the
fallback model.
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


def _mk_response_raw(content: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=400),
    )


def _mk_response(items: list[dict[str, Any]]) -> Any:
    return _mk_response_raw(json.dumps({"items": items}))


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


@pytest.fixture
def _settings(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "true")
    monkeypatch.setenv("OPENAI_VISION_MODEL_PRIMARY", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_VISION_MODEL_FALLBACK", "gpt-4o-2024-08-06")
    monkeypatch.setenv("VISION_CONFIDENCE_THRESHOLD", "0.7")
    monkeypatch.setenv("VISION_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("VISION_LOW_DETAIL_MAX_DIM", "500")
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_truncated_primary_escalates_to_fallback(
    _no_cost_cap,
    _no_breaker,
    _settings,
) -> None:
    # Truncated JSON: missing closing bracket.
    truncated = '{"items":[{"name":"sopa","estimated_amount_g":200'
    rich_items = [
        {
            "name": "sopa de pollo",
            "estimated_amount_g": 250,
            "kcal": 180,
            "protein_g": 12,
            "carbs_g": 18,
            "fat_g": 5,
            "confidence": 0.92,
        }
    ]
    create = AsyncMock(
        side_effect=[
            _mk_response_raw(truncated),
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

    # Primary parse failed -> treated as empty -> cascade escalated.
    assert create.await_count == 2
    assert create.await_args_list[0].kwargs["model"] == "gpt-4o-mini"
    assert create.await_args_list[1].kwargs["model"] == "gpt-4o-2024-08-06"
    assert len(items) == 1
    assert items[0].name == "sopa de pollo"
