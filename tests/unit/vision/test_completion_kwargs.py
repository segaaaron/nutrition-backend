"""GPT-5 / o-series call-parameter compatibility (regression for the 400
``Unsupported parameter: 'max_tokens'`` / ``'temperature'`` errors).

GPT-5 and the o-series reject the legacy ``max_tokens`` param (require
``max_completion_tokens``) and reject any ``temperature`` other than the
default 1. Older gpt-4o* models keep the legacy params for deterministic
output. These tests lock that split so a model bump can't silently break
the vision call again.
"""

from __future__ import annotations

import pytest

from app.vision.infrastructure.openai_vision import (
    _completion_kwargs,
    _model_is_gpt5_family,
)


@pytest.mark.parametrize(
    "model",
    ["gpt-5-mini", "gpt-5.1", "gpt-5", "GPT-5-Mini", "o1", "o3-mini", "o4"],
)
def test_gpt5_family_uses_max_completion_tokens_and_no_temperature(model: str) -> None:
    assert _model_is_gpt5_family(model) is True
    kw = _completion_kwargs(model, 4000)
    assert kw == {
        "max_completion_tokens": 4000,
        # reasoning_effort + verbosity are env-tunable (config defaults below).
        "extra_body": {"reasoning_effort": "low", "verbosity": "low"},
    }
    # Legacy params MUST be absent — their presence 400s on GPT-5.
    assert "max_tokens" not in kw
    assert "temperature" not in kw
    # Defaults: reasoning_effort="low" (minimal/medium measured EMPTY on the real
    # vision prompt; "low" detects reliably) and verbosity="low" (~30% fewer
    # output tokens = faster, correct for an extraction task).
    assert kw["extra_body"]["reasoning_effort"] == "low"
    assert kw["extra_body"]["verbosity"] == "low"


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4o-2024-08-06", "gpt-4o"])
def test_legacy_models_keep_max_tokens_and_temperature(model: str) -> None:
    assert _model_is_gpt5_family(model) is False
    kw = _completion_kwargs(model, 1200)
    assert kw == {"max_tokens": 1200, "temperature": 0.0}
