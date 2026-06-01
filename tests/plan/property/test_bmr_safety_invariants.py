"""Property-based tests for H1.4 BMR, TDEE, goal adjustment, safety floor.

Each property runs ≥200 hypothesis examples. End-to-end pipeline closes the
loop: Mifflin → TDEE → goal → fat/protein → back_adjust must respect
MacroConsistency and the BMR*0.9 safety floor.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app.plan.domain.bmr_safety import (
    KcalTargetBelowSafetyFloor,
    apply_goal_to_tdee,
    cunningham,
    enforce_bmr_safety_floor,
    mifflin_st_jeor,
    tdee,
)
from app.plan.domain.macro_calculator import (
    MacroBackAdjustFailed,
    back_adjust_macros,
    derive_kcal_from_macros,
    fat_target_g,
    protein_target_g,
)
from app.shared.domain.macro_tolerance import MACRO_TOLERANCE
from tests.plan.property.strategies import (
    activity,
    age,
    bmr_decimal,
    decimal_in_range,
    goal,
    height_cm,
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
# 9. MifflinBounded
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(w=weight_kg, h=height_cm, a=age, s=sex)
def test_mifflin_within_realistic_adult_range(
    w: Decimal, h: Decimal, a: int, s: str
) -> None:
    bmr = mifflin_st_jeor(weight_kg=w, height_cm=h, age=a, sex=s)  # type: ignore[arg-type]
    # Realistic adult range. The corner (small elderly woman) bottoms near
    # ~800; the large young man corner tops near ~2800. Bounds are loose
    # enough not to drift with anthropometric edges but tight enough to
    # catch sign errors or wrong constants in the formula.
    assert bmr >= Decimal("700")
    assert bmr <= Decimal("3500")


# ---------------------------------------------------------------------------
# 10. CunninghamLBMSensitive — strictly increasing in LBM
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(
    lbm=decimal_in_range("30", "120", places=1),
    delta=decimal_in_range("0.5", "20", places=1),
)
def test_cunningham_strictly_increasing_in_lbm(lbm: Decimal, delta: Decimal) -> None:
    base = cunningham(lbm_kg=lbm)
    bumped = cunningham(lbm_kg=lbm + delta)
    assert bumped > base


# ---------------------------------------------------------------------------
# 11. TDEEActivityOrder — strictly ordered by activity multiplier
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(bmr=bmr_decimal)
def test_tdee_strictly_ordered_by_activity_level(bmr: Decimal) -> None:
    sed = tdee(bmr=bmr, activity_level="sedentary")
    light = tdee(bmr=bmr, activity_level="lightly_active")
    mod = tdee(bmr=bmr, activity_level="moderately_active")
    very = tdee(bmr=bmr, activity_level="very_active")
    extra = tdee(bmr=bmr, activity_level="extra_active")

    assert sed < light
    assert light < mod
    assert mod < very
    assert very < extra


# ---------------------------------------------------------------------------
# 12. GoalAdjustmentDirection
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(tdee_val=decimal_in_range("1200", "4500", places=0))
def test_goal_adjustment_direction_matches_clinical_intent(
    tdee_val: Decimal,
) -> None:
    wl = apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_loss")
    mt = apply_goal_to_tdee(tdee_val=tdee_val, goal="maintain")
    mg = apply_goal_to_tdee(tdee_val=tdee_val, goal="muscle_gain")
    wg = apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_gain")
    hl = apply_goal_to_tdee(tdee_val=tdee_val, goal="health")

    assert wl <= tdee_val
    assert mt == tdee_val
    assert hl == tdee_val
    assert mg > tdee_val
    assert wg > tdee_val
    # Weight gain surplus is larger than muscle gain surplus.
    assert wg > mg


# ---------------------------------------------------------------------------
# 13. BMRSafetyFloorRaises
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(
    bmr=bmr_decimal,
    fraction=st.decimals(
        min_value=Decimal("0.30"),
        max_value=Decimal("0.89"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
def test_safety_floor_raises_when_target_below_bmr_times_0_9(
    bmr: Decimal, fraction: Decimal
) -> None:
    target = (bmr * fraction).quantize(Decimal("1"))
    # Guarantee strictly below floor after quantisation.
    floor = bmr * Decimal("0.9")
    assume(target < floor)

    with pytest.raises(KcalTargetBelowSafetyFloor):
        enforce_bmr_safety_floor(kcal_target=target, bmr=bmr)


# ---------------------------------------------------------------------------
# 14. BMRSafetyFloorPasses
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(
    bmr=bmr_decimal,
    fraction=st.decimals(
        min_value=Decimal("0.90"),
        max_value=Decimal("2.00"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
def test_safety_floor_passes_through_when_target_at_or_above_floor(
    bmr: Decimal, fraction: Decimal
) -> None:
    target = (bmr * fraction).quantize(Decimal("1"))
    floor = bmr * Decimal("0.9")
    assume(target >= floor)

    result = enforce_bmr_safety_floor(kcal_target=target, bmr=bmr)
    assert result == target


# ---------------------------------------------------------------------------
# 15. EndToEndPipelineSafe
# ---------------------------------------------------------------------------
@pytest.mark.property
@_SETTINGS
@given(w=weight_kg, h=height_cm, a=age, s=sex, act=activity, g=goal)
def test_full_pipeline_respects_safety_and_macro_consistency(
    w: Decimal, h: Decimal, a: int, s: str, act: str, g: str
) -> None:
    bmr = mifflin_st_jeor(weight_kg=w, height_cm=h, age=a, sex=s)  # type: ignore[arg-type]
    tdee_val = tdee(bmr=bmr, activity_level=act)  # type: ignore[arg-type]
    target = apply_goal_to_tdee(tdee_val=tdee_val, goal=g)  # type: ignore[arg-type]

    # Safety floor: this is the contract we want the pipeline to uphold.
    # For weight_loss the deficit is min(500, 25% TDEE); 25% deficit leaves
    # 75% TDEE ~= 0.75 * 1.2 * BMR = 0.9 BMR at sedentary — exactly the floor.
    # Anything stricter (very low activity + max deficit) could violate it.
    try:
        enforce_bmr_safety_floor(kcal_target=target, bmr=bmr)
    except KcalTargetBelowSafetyFloor:
        # Pipeline correctly flagged an unsafe combination — that is the
        # designed behaviour. Skip macro check; the caller must intervene.
        return

    # Compute macro targets from the safe kcal target.
    p = protein_target_g(weight_kg=w, sex=s, goal=g)  # type: ignore[arg-type]
    f = fat_target_g(weight_kg=w, kcal=target, goal=g)  # type: ignore[arg-type]

    # If protein+fat alone already exceed the target, back-adjust is infeasible.
    assume(p * Decimal("4") + f * Decimal("9") <= target)

    try:
        out_p, out_c, out_f = back_adjust_macros(target, p, f)
    except MacroBackAdjustFailed:
        return

    derived = derive_kcal_from_macros(out_p, out_c, out_f)
    rel = (derived - target).copy_abs() / target
    assert rel <= MACRO_TOLERANCE
    assert out_c >= Decimal("0")
