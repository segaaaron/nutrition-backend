"""Sprint A2 — expected weekly weight change from energy balance."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.nutrition.domain.weight_projection import expected_weekly_change


def test_deficit_predicts_loss() -> None:
    # 500 kcal/day deficit → (−500 * 7) / 7700 = −0.4545 → −0.45 kg/week
    p = expected_weekly_change(kcal_target=2000, tdee=2500)
    assert p.weekly_kg == Decimal("-0.45")
    assert p.ci_low_kg < p.weekly_kg < p.ci_high_kg  # band brackets the point


def test_surplus_predicts_gain() -> None:
    p = expected_weekly_change(kcal_target=2800, tdee=2500)
    assert p.weekly_kg == Decimal("0.27")  # (300*7)/7700
    assert p.weekly_kg > 0


def test_maintenance_is_zero_with_zero_width_band() -> None:
    p = expected_weekly_change(kcal_target=2200, tdee=2200)
    assert p.weekly_kg == Decimal("0.00")
    assert p.ci_low_kg == Decimal("0.00") == p.ci_high_kg


def test_ci_band_is_25_percent() -> None:
    p = expected_weekly_change(kcal_target=2000, tdee=2500)
    margin = abs(p.weekly_kg) * Decimal("0.25")
    assert float(p.ci_high_kg - p.weekly_kg) == pytest.approx(float(margin), abs=0.01)


@given(
    kcal_target=st.integers(min_value=800, max_value=4500),
    tdee=st.integers(min_value=1000, max_value=4500),
)
def test_property_sign_matches_energy_balance(kcal_target: int, tdee: int) -> None:
    p = expected_weekly_change(kcal_target=kcal_target, tdee=tdee)
    if kcal_target > tdee:
        assert p.weekly_kg >= 0
    elif kcal_target < tdee:
        assert p.weekly_kg <= 0
    else:
        assert p.weekly_kg == Decimal("0.00")
    # band always brackets (or equals at maintenance) the point estimate
    assert p.ci_low_kg <= p.weekly_kg <= p.ci_high_kg
