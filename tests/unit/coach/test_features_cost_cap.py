"""Regression guard for the cost-cap-blocked path in coach `_mini_completion`.

A latent NameError (`_log` vs `log`) lived in this error handler and would have
crashed the coach with `NameError` INSTEAD of gracefully returning "" whenever
the cost cap blocked a feature call. The path had no test — that is exactly why
the bug survived. This locks the correct behavior: cap raises → log + return "".
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import app.coach.application.features as feat


@pytest.mark.asyncio
async def test_cost_cap_blocked_returns_empty_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(**_kwargs: object) -> None:
        raise RuntimeError("cost_cap_exceeded")

    class _Settings:
        openai_chat_model = "gpt-4o-mini"

    monkeypatch.setattr(feat, "pre_check", _raise)
    monkeypatch.setattr(feat, "estimate_input_cost", lambda *_a, **_k: 0.01)
    monkeypatch.setattr(feat, "get_settings", lambda: _Settings())

    # Must return "" gracefully — NOT raise NameError (the fixed F821 bug) nor
    # the underlying RuntimeError.
    result = await feat._mini_completion("hello", user_id=uuid4())
    assert result == ""


@pytest.mark.asyncio
async def test_cost_cap_blocked_handles_anon_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(**_kwargs: object) -> None:
        raise RuntimeError("cost_cap_exceeded")

    class _Settings:
        openai_chat_model = "gpt-4o-mini"

    monkeypatch.setattr(feat, "pre_check", _raise)
    monkeypatch.setattr(feat, "estimate_input_cost", lambda *_a, **_k: 0.01)
    monkeypatch.setattr(feat, "get_settings", lambda: _Settings())

    # user_id=None exercises the `if user_id else "anon"` branch in the log call.
    result = await feat._mini_completion("hello", user_id=None)
    assert result == ""
