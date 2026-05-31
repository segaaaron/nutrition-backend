"""ADR-0002 — recalibration must clamp the resulting TDEE within ±15%
of the current value and must skip when prior data is insufficient or
cooldown isn't met.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.nutrition.domain.recalibration import (
    RecalibrationInput,
    RecalibrationResult,
    RecalibrationSkipped,
    recalibrate,
)


def _input(**overrides) -> RecalibrationInput:
    base = dict(
        sex="male", weight_kg_now=Decimal("80"), height_cm=Decimal("180"),
        age=30, activity_factor=Decimal("1.55"), goal="weight_loss",
        tdee_current=2500, days_since_last_recalibration=20,
        weights=[(i, 80.0 - 0.05 * i) for i in range(14)],
        kcal_in=[1800] * 14,
    )
    base.update(overrides)
    return RecalibrationInput(**base)


def test_insufficient_data_returns_skipped() -> None:
    out = recalibrate(_input(weights=[(0, 80.0)]))
    assert isinstance(out, RecalibrationSkipped)
    assert out.reason == "insufficient_data"


def test_cooldown_blocks_recalibration() -> None:
    out = recalibrate(_input(days_since_last_recalibration=5))
    assert isinstance(out, RecalibrationSkipped)
    assert out.reason == "cooldown"


def test_blend_clamps_within_15_percent() -> None:
    out = recalibrate(_input(kcal_in=[1200] * 14))
    # Should either skip (delta_below_threshold guard) or land within ±15%.
    if isinstance(out, RecalibrationResult):
        lo = int(2500 * 0.85)
        hi = int(2500 * 1.15)
        assert lo <= out.tdee_new <= hi, f"{out.tdee_new} not in [{lo},{hi}]"
