"""R3 — Adaptive thermogenesis (Müller 2015) tests."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.nutrition.domain.adaptive_thermogenesis import (
    AT_CAP_FRACTION,
    at_correction,
)


def test_at_zero_when_deficit_under_21_days():
    out = at_correction(days_in_deficit=14, avg_deficit_kcal=Decimal("500"), tdee=Decimal("2500"))
    assert out == Decimal("0")


def test_at_zero_at_exactly_20_days():
    out = at_correction(days_in_deficit=20, avg_deficit_kcal=Decimal("500"), tdee=Decimal("2500"))
    assert out == Decimal("0")


def test_at_activates_at_21_days():
    out = at_correction(days_in_deficit=21, avg_deficit_kcal=Decimal("500"), tdee=Decimal("2500"))
    # raw = -0.06 * 500 * 21/14 = -45
    assert out == Decimal("-45.00")


def test_at_caps_at_15pct_tdee():
    """Heavy sustained deficit must clamp to −15% × TDEE."""
    out = at_correction(days_in_deficit=120, avg_deficit_kcal=Decimal("1000"), tdee=Decimal("2500"))
    # raw = -0.06 * 1000 * 120/14 = -514.28; cap = -0.15 * 2500 = -375
    assert out == Decimal("-375.00")


def test_at_muller_anchor_28d_500_deficit():
    """Müller MJ et al. 2015 (Obes Facts 8:165) Table 2 — representative
    subject in sustained deficit shows AT ~ −60 to −90 kcal/d at ~28d.
    Our model: -0.06 * 500 * 28/14 = -60 kcal/d. Anchors at lower bound."""
    out = at_correction(days_in_deficit=28, avg_deficit_kcal=Decimal("500"), tdee=Decimal("2500"))
    assert out == Decimal("-60.00")


_S = settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@_S
@given(
    days=st.integers(min_value=0, max_value=365),
    deficit=st.decimals(min_value=Decimal("0"), max_value=Decimal("1500"), places=0),
    tdee=st.decimals(min_value=Decimal("1200"), max_value=Decimal("4000"), places=0),
)
def test_property_at_always_non_positive(
    days: int,
    deficit: Decimal,
    tdee: Decimal,
) -> None:
    out = at_correction(days_in_deficit=days, avg_deficit_kcal=deficit, tdee=tdee)
    assert out <= Decimal("0")


@_S
@given(
    days=st.integers(min_value=21, max_value=365),
    deficit=st.decimals(min_value=Decimal("100"), max_value=Decimal("1500"), places=0),
    tdee=st.decimals(min_value=Decimal("1200"), max_value=Decimal("4000"), places=0),
)
def test_property_at_magnitude_bounded_by_15pct_tdee(
    days: int,
    deficit: Decimal,
    tdee: Decimal,
) -> None:
    out = at_correction(days_in_deficit=days, avg_deficit_kcal=deficit, tdee=tdee)
    assert abs(out) <= AT_CAP_FRACTION * tdee + Decimal("0.01")
