"""Pre-filter cost accounting: verify the provider calls record_usage with
the cheap mini model name and a small token count.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.vision.infrastructure import openai_vision as ov


def _resp_accept() -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"accept": true, "reason": "food"}',
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=180, completion_tokens=12),
    )


@pytest.mark.asyncio
async def test_prefilter_records_usage_with_mini_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pre_calls: list[dict] = []
    rec_calls: list[dict] = []

    async def _pre(**kw):
        pre_calls.append(kw)

    async def _rec(**kw):
        rec_calls.append(kw)
        return 0.0

    monkeypatch.setattr(ov, "pre_check", _pre)
    monkeypatch.setattr(ov, "record_usage", _rec)

    create = AsyncMock(return_value=_resp_accept())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        accept, reason = await provider.is_food_image(
            image_bytes=b"\x89PNG_FAKE_BYTES_",
            mime="image/webp",
            user_id=None,
        )

    assert accept is True
    assert reason == "food"
    # Pre-check ran at the tiny estimate.
    assert len(pre_calls) == 1
    assert pre_calls[0]["estimate_usd"] == ov.PREFILTER_COST_ESTIMATE_USD
    # Usage recorded at the mini model with the reported token counts.
    assert len(rec_calls) == 1
    assert rec_calls[0]["model"] == "gpt-4o-mini"
    assert rec_calls[0]["in_tok"] == 180
    assert rec_calls[0]["out_tok"] == 12
    # Output token cap is small (<= 30) — sanity ceiling.
    assert ov.PREFILTER_MAX_OUTPUT_TOKENS <= 30

    # The mini model call used detail=low and the cheap model.
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["max_tokens"] == ov.PREFILTER_MAX_OUTPUT_TOKENS
    img_part = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
    assert img_part["image_url"]["detail"] == "low"


@pytest.mark.asyncio
async def test_prefilter_unknown_reason_tag_falls_back_to_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok(**_kw):
        return None

    monkeypatch.setattr(ov, "pre_check", _ok)

    async def _rec(**_kw):
        return 0.0

    monkeypatch.setattr(ov, "record_usage", _rec)

    rogue = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"accept": true, "reason": "some_made_up_tag"}',
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=180, completion_tokens=12),
    )
    create = AsyncMock(return_value=rogue)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(ov, "_get_client", return_value=client):
        provider = ov.OpenAIVisionProvider()
        accept, reason = await provider.is_food_image(
            image_bytes=b"x",
            mime="image/webp",
            user_id=None,
        )
    assert accept is True
    assert reason == "uncertain"
