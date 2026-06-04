"""Hydration target tests (R8 — condition caps)."""

from __future__ import annotations

from decimal import Decimal

from app.nutrition.domain.hydration import (
    CHF_FLUID_CAP_ML,
    CKD_FLUID_CAP_ML,
    compute_water_ml,
)


def test_baseline_heavy_user_no_condition():
    # 80 kg sedentary → 35 * 80 = 2800
    assert compute_water_ml(weight_kg=Decimal("80"), activity_factor=Decimal("1.20")) == 2800


def test_ckd_caps_at_1500():
    out = compute_water_ml(
        weight_kg=Decimal("100"),
        activity_factor=Decimal("1.55"),
        conditions=frozenset({"ckd"}),
    )
    assert out <= CKD_FLUID_CAP_ML
    assert out == 1500


def test_chf_caps_at_1500():
    out = compute_water_ml(
        weight_kg=Decimal("90"),
        activity_factor=Decimal("1.55"),
        conditions=frozenset({"chf"}),
    )
    assert out <= CHF_FLUID_CAP_ML
    assert out == 1500


def test_conditions_optional_backward_compat():
    """Existing call sites without `conditions` kwarg keep working."""
    out = compute_water_ml(weight_kg=Decimal("70"), activity_factor=Decimal("1.375"))
    assert out > 0


def test_ckd_cap_does_not_inflate_low_target():
    # 30 kg child (out of scope but math sanity): 1050 base < 1500 floor
    # floor wins, then cap holds.
    out = compute_water_ml(
        weight_kg=Decimal("30"),
        activity_factor=Decimal("1.20"),
        conditions=frozenset({"ckd"}),
    )
    # Floor 1500 then capped 1500 — equal.
    assert out == 1500


def test_multiple_conditions_with_ckd_still_capped():
    out = compute_water_ml(
        weight_kg=Decimal("110"),
        activity_factor=Decimal("1.90"),
        conditions=frozenset({"ckd", "hypertension"}),
    )
    assert out == 1500
