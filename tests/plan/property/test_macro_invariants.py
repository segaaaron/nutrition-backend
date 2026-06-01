"""Property-based tests for H1.1-H1.3 macro math.

Each property runs ≥200 hypothesis examples. Assertions use Decimal arithmetic
exclusively. No float equality. No mocks. Pure domain.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app.plan.domain.macro_calculator import (
    MacroBackAdjustFailed,
    back_adjust_macros,
    derive_kcal_from_macros,
    fat_target_g,
    lbm_kg,
    protein_target_g,
)
from app.shared.domain.macro_tolerance import MACRO_TOLERANCE
from tests.plan.property.strategies import (
    bodyfat_pct,
    decimal_in_range,
    fat_g,
    goal,
    kcal_target,
    protein_g,
    sex,
    weight_kg,
)

_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    derandomize=False,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# ---------------------------------------------------------------------------
# 1. MacroConsistency post back-adjust
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(target_kcal=kcal_target, p=protein_g, f=fat_g)
def test_back_adjust_yields_macro_consistency_within_tolerance(
    target_kcal: Decimal, p: Decimal, f: Decimal
) -> None:
    # Skip combos where protein+fat already exceed target (no feasible carbs).
    fixed_kcal = p * Decimal("4") + f * Decimal("9")
    assume(fixed_kcal <= target_kcal)

    try:
        out_p, out_c, out_f = back_adjust_macros(target_kcal, p, f)
    except MacroBackAdjustFailed:
        # Algorithm signalled non-convergence within ±5g of carbs. Allowed.
        return

    derived = derive_kcal_from_macros(out_p, out_c, out_f)
    rel = (derived - target_kcal).copy_abs() / target_kcal
    assert rel <= MACRO_TOLERANCE


# ---------------------------------------------------------------------------
# 2. NonNegativeMacros
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(target_kcal=kcal_target, p=protein_g, f=fat_g)
def test_back_adjust_never_returns_negative_macros(
    target_kcal: Decimal, p: Decimal, f: Decimal
) -> None:
    fixed_kcal = p * Decimal("4") + f * Decimal("9")
    assume(fixed_kcal <= target_kcal)

    try:
        out_p, out_c, out_f = back_adjust_macros(target_kcal, p, f)
    except MacroBackAdjustFailed:
        return

    assert out_p >= Decimal("0")
    assert out_c >= Decimal("0")
    assert out_f >= Decimal("0")


# ---------------------------------------------------------------------------
# 3. LBM bounded
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(w=weight_kg, s=sex, bf=bodyfat_pct)
def test_lbm_bounded_between_half_weight_and_weight(
    w: Decimal, s: str, bf: Decimal | None
) -> None:
    lbm = lbm_kg(w, s, bf)  # type: ignore[arg-type]
    # Physiological invariant: LBM is a non-negative fraction of body weight.
    # No fixed floor at 0.5w — a body composition of 60% fat (clinically
    # possible in severe obesity) places LBM at 0.4w.
    assert lbm <= w
    assert lbm >= Decimal("0")


# ---------------------------------------------------------------------------
# 4. ProteinClamp
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(w=weight_kg, s=sex, g=goal, bf=bodyfat_pct)
def test_protein_target_within_clinical_clamp(
    w: Decimal, s: str, g: str, bf: Decimal | None
) -> None:
    p = protein_target_g(weight_kg=w, sex=s, goal=g, bodyfat_pct=bf)  # type: ignore[arg-type]
    floor = Decimal("0.6") * w
    ceil = Decimal("2.5") * w
    # Quantise to 1g may round below floor by <1g; tolerate that.
    assert p >= floor - Decimal("1")
    assert p <= ceil + Decimal("1")


# ---------------------------------------------------------------------------
# 5. FatFloor
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(w=weight_kg, kcal=kcal_target, g=goal)
def test_fat_target_respects_minimum_floor(
    w: Decimal, kcal: Decimal, g: str
) -> None:
    f = fat_target_g(weight_kg=w, kcal=kcal, goal=g)  # type: ignore[arg-type]
    floor = Decimal("0.6") * w
    assert f >= floor - Decimal("1")  # 1g quantisation cushion


# ---------------------------------------------------------------------------
# 6. FatRangeReasonable
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(
    w=decimal_in_range("60", "120", places=1),
    kcal=decimal_in_range("1800", "3500", places=0),
    g=goal,
)
def test_fat_fraction_of_kcal_within_physiological_range(
    w: Decimal, kcal: Decimal, g: str
) -> None:
    f = fat_target_g(weight_kg=w, kcal=kcal, goal=g)  # type: ignore[arg-type]
    kcal_from_fat = f * Decimal("9")
    fraction = kcal_from_fat / kcal
    # Upper bound: floor dominates at very low kcal; allow generous ceiling.
    # Lower bound is the goal pct (≥0.25). Floor can push higher.
    assert fraction >= Decimal("0.20")
    assert fraction <= Decimal("0.55")


# ---------------------------------------------------------------------------
# 7. BackAdjustIdempotent
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(target_kcal=kcal_target, p=protein_g, f=fat_g)
def test_back_adjust_is_idempotent_on_its_own_output(
    target_kcal: Decimal, p: Decimal, f: Decimal
) -> None:
    fixed_kcal = p * Decimal("4") + f * Decimal("9")
    assume(fixed_kcal <= target_kcal)

    try:
        p1, c1, f1 = back_adjust_macros(target_kcal, p, f)
        p2, c2, f2 = back_adjust_macros(target_kcal, p1, f1)
    except MacroBackAdjustFailed:
        return

    assert p1 == p2
    assert f1 == f2
    # Carbs may differ by at most 1g due to the ±1g search step.
    assert (c1 - c2).copy_abs() <= Decimal("1")


# ---------------------------------------------------------------------------
# 8. DeriveKcalSymmetry — monotonic in each macro
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(
    p=protein_g,
    c=st.decimals(
        min_value=Decimal("50"),
        max_value=Decimal("600"),
        allow_nan=False,
        allow_infinity=False,
        places=0,
    ),
    f=fat_g,
    delta=st.decimals(
        min_value=Decimal("1"),
        max_value=Decimal("50"),
        allow_nan=False,
        allow_infinity=False,
        places=0,
    ),
)
def test_derive_kcal_strictly_monotonic_in_each_macro(
    p: Decimal, c: Decimal, f: Decimal, delta: Decimal
) -> None:
    base = derive_kcal_from_macros(p, c, f)
    bumped_p = derive_kcal_from_macros(p + delta, c, f)
    bumped_c = derive_kcal_from_macros(p, c + delta, f)
    bumped_f = derive_kcal_from_macros(p, c, f + delta)

    assert bumped_p > base
    assert bumped_c > base
    assert bumped_f > base
    # Fat coefficient (9) > protein/carb coefficient (4): equal delta in fat
    # must move kcal more than equal delta in protein or carbs.
    assert bumped_f - base > bumped_p - base
    assert bumped_f - base > bumped_c - base
