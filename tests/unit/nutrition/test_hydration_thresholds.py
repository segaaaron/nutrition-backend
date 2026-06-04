"""D14 — hydration factor steps are threshold-based, not equality-keyed."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.nutrition.domain.hydration import _activity_bonus_ml, compute_water_ml

# -- Exact-step parity with the original equality-keyed table ----------------


@pytest.mark.parametrize(
    "af, expected_bonus",
    [
        (Decimal("1.20"), 0),
        (Decimal("1.375"), 350),
        (Decimal("1.55"), 700),
        (Decimal("1.725"), 1050),
        (Decimal("1.90"), 1400),
    ],
)
def test_exact_pal_thresholds_map_to_expected_bonus(af: Decimal, expected_bonus: int) -> None:
    assert _activity_bonus_ml(af) == expected_bonus


# -- Threshold semantics — non-canonical Decimals still resolve --------------


def test_non_canonical_decimal_still_resolves() -> None:
    """`Decimal('1.5500')` and `Decimal('1.55000001')` both >= 1.55 threshold.

    Old equality-keyed dict would silently fall through to bonus=0 here.
    """
    assert _activity_bonus_ml(Decimal("1.5500")) == 700
    assert _activity_bonus_ml(Decimal("1.55000001")) == 700


def test_below_sedentary_returns_zero_bonus() -> None:
    assert _activity_bonus_ml(Decimal("1.0")) == 0
    assert _activity_bonus_ml(Decimal("1.199")) == 0


def test_above_top_threshold_saturates_at_max() -> None:
    assert _activity_bonus_ml(Decimal("2.50")) == 1400


def test_between_thresholds_uses_lower_step() -> None:
    # 1.50 is between 1.375 and 1.55 → 350 (the 1.375 step).
    assert _activity_bonus_ml(Decimal("1.50")) == 350
    # 1.70 between 1.55 and 1.725 → 700 (the 1.55 step).
    assert _activity_bonus_ml(Decimal("1.70")) == 700


# -- Property: any af in [1.2, 2.0] maps to a deterministic non-None step ----


@given(
    st.decimals(
        min_value=Decimal("1.20"),
        max_value=Decimal("2.00"),
        places=4,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_property_pal_in_range_yields_deterministic_bonus(af: Decimal) -> None:
    out1 = _activity_bonus_ml(af)
    out2 = _activity_bonus_ml(af)
    assert out1 == out2  # deterministic
    assert out1 in {0, 350, 700, 1050, 1400}  # one of the canonical steps


# -- End-to-end via compute_water_ml -----------------------------------------


def test_compute_water_ml_accepts_off_threshold_decimal() -> None:
    """Sanity check: a Decimal('1.60') falls into the 1.55 step (700 mL bonus)."""
    out = compute_water_ml(weight_kg=Decimal("70"), activity_factor=Decimal("1.60"))
    # base = 35 * 70 = 2450; bonus = 700; target = 3150 (within clamp).
    assert out == 2450 + 700
