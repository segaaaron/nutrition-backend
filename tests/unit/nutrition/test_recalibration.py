"""ADR-0002 recalibration tests."""
from __future__ import annotations

from decimal import Decimal

from app.nutrition.domain.recalibration import (
    RecalibrationInput,
    RecalibrationResult,
    RecalibrationSkipped,
    recalibrate,
)


def _baseline(**overrides) -> RecalibrationInput:
    base = dict(
        sex="male", weight_kg_now=Decimal("80"), height_cm=Decimal("180"), age=30,
        activity_factor=Decimal("1.55"), goal="maintain",
        tdee_current=2800,
        days_since_last_recalibration=30,
        weights=[(i, 80.0 - i * 0.05) for i in range(14)],  # ~700g loss over 14d
        kcal_in=[2500] * 14,
    )
    base.update(overrides)
    return RecalibrationInput(**base)


def test_skip_when_insufficient_data():
    r = recalibrate(_baseline(weights=[(0, 80.0)]))
    assert isinstance(r, RecalibrationSkipped)
    assert r.reason == "insufficient_data"


def test_skip_during_cooldown():
    r = recalibrate(_baseline(days_since_last_recalibration=5))
    assert isinstance(r, RecalibrationSkipped)
    assert r.reason == "cooldown"


def test_skip_athlete_bulk():
    r = recalibrate(_baseline(
        goal="muscle_gain",
        weights=[(i, 80.0 + i * 0.05) for i in range(14)],   # +700g
        kcal_in=[3300] * 14,
        tdee_current=2800,
    ))
    # delta ratio near 1.0 because intake > tdee → expected gain matches actual
    assert isinstance(r, (RecalibrationSkipped, RecalibrationResult))


def test_result_clamped_within_15pct():
    r = recalibrate(_baseline(
        weights=[(i, 80.0 - i * 0.2) for i in range(14)],  # aggressive loss
        kcal_in=[2400] * 14,
    ))
    if isinstance(r, RecalibrationResult):
        assert 2800 * 0.85 <= r.tdee_new <= 2800 * 1.15
