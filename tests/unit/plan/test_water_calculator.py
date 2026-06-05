"""Tests for app.plan.domain.water_calculator — NOVA hybrid hydration.

Coverage:
    * Edge cases (exact numeric expectations).
    * Property-based invariants (hypothesis):
        - Hard caps [1500, 4000] hold ∀ inputs.
        - CKD/heart_failure ⇒ total_ml <= 1500 ALWAYS.
        - Determinism.
        - Monotonicity in weight + kcal (under fixed otros).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.water_calculator import (
    MEDICAL_OVERRIDE_CAP_ML,
    SAFETY_MAX_ML,
    SAFETY_MIN_ML,
    WaterTarget,
    calculate_water_target,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies.
# ---------------------------------------------------------------------------

_weight_strat = st.decimals(
    min_value=Decimal("30"),
    max_value=Decimal("250"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_kcal_strat = st.integers(min_value=800, max_value=6000)
_activity_strat = st.sampled_from(
    ["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
)
_region_strat = st.sampled_from(["latam", "eu", "us", "asia"])
_month_strat = st.integers(min_value=1, max_value=12)
_goal_strat = st.sampled_from(
    ["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
)


def _call(**overrides: object) -> WaterTarget:
    defaults: dict[str, object] = dict(
        weight_kg=Decimal("70"),
        kcal_daily=2000,
        activity="sedentary",
        region="eu",
        month=6,
        goal="maintain",
        conditions=frozenset(),
        pregnant=False,
        lactating=False,
    )
    defaults.update(overrides)
    return calculate_water_target(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Exact edge-case numbers (proving the spec literally).
# ---------------------------------------------------------------------------


def test_athlete_100kg_4000kcal_very_active_muscle_gain_hits_max_cap() -> None:
    # base 100*35=3500 ; kcal_boost (4000-2000)*.5=1000 ; +1000 very_active
    # +500 muscle_gain ; total 6000 → clamp 4000.
    t = _call(
        weight_kg=Decimal("100"),
        kcal_daily=4000,
        activity="very_active",
        goal="muscle_gain",
    )
    assert t.total_ml == 4000
    assert t.capped_by_safety is True
    assert t.capped_by_medical is False


def test_sedentary_50kg_1200kcal_weight_loss_hits_min_cap() -> None:
    # base 50*35=1750 ; kcal_boost max(0,(1200-2000)*.5)=0 ; +250 wl ⇒ 2000.
    # That's above 1500 so no clamp — adjust to truly low scenario.
    t = _call(
        weight_kg=Decimal("40"),
        kcal_daily=1000,
        activity="sedentary",
        goal="maintain",
    )
    # base 40*35=1400 ; kcal_boost 0 ; total 1400 → clamp UP to 1500.
    assert t.total_ml == 1500
    assert t.capped_by_safety is True
    assert t.capped_by_medical is False


def test_ckd_user_90kg_3500kcal_very_active_medical_override_to_1500() -> None:
    t = _call(
        weight_kg=Decimal("90"),
        kcal_daily=3500,
        activity="very_active",
        conditions=frozenset({"ckd"}),
    )
    assert t.total_ml == 1500
    assert t.capped_by_medical is True


def test_heart_failure_override_dominates() -> None:
    t = _call(
        weight_kg=Decimal("80"),
        kcal_daily=2500,
        activity="moderately_active",
        conditions=frozenset({"heart_failure"}),
    )
    assert t.total_ml <= 1500
    assert t.capped_by_medical is True


def test_pregnant_and_lactating_both_add_1000_modifier() -> None:
    t_neither = _call()
    t_both = _call(pregnant=True, lactating=True)
    assert t_both.total_ml - t_neither.total_ml == 1000


def test_latam_hot_month_december_adds_500() -> None:
    t_no = _call(region="latam", month=6)
    t_yes = _call(region="latam", month=12)
    assert t_yes.total_ml - t_no.total_ml == 500


def test_latam_cool_month_june_no_boost() -> None:
    t_jun = _call(region="latam", month=6)
    t_eu_jun = _call(region="eu", month=6)
    assert t_jun.total_ml == t_eu_jun.total_ml


def test_non_latam_december_no_boost() -> None:
    t_eu = _call(region="eu", month=12)
    t_us = _call(region="us", month=12)
    assert t_eu.total_ml == t_us.total_ml


def test_glass_count_ceil_division() -> None:
    t = _call(weight_kg=Decimal("70"), kcal_daily=2000)
    # 70*35=2450 → ceil(2450/250)=10
    assert t.total_ml == 2450
    assert t.n_glasses == 10


def test_invalid_inputs_raise_valueerror() -> None:
    with pytest.raises(ValueError, match="weight_kg"):
        _call(weight_kg=Decimal("0"))
    with pytest.raises(ValueError, match="kcal_daily"):
        _call(kcal_daily=0)
    with pytest.raises(ValueError, match="month"):
        _call(month=0)
    with pytest.raises(ValueError, match="month"):
        _call(month=13)
    with pytest.raises(ValueError, match="glass_ml"):
        _call(glass_ml=0)


# ---------------------------------------------------------------------------
# Property-based invariants.
# ---------------------------------------------------------------------------


@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
@given(
    weight=_weight_strat,
    kcal=_kcal_strat,
    activity=_activity_strat,
    region=_region_strat,
    month=_month_strat,
    goal=_goal_strat,
    pregnant=st.booleans(),
    lactating=st.booleans(),
)
def test_hard_caps_always_hold(
    weight: Decimal,
    kcal: int,
    activity: str,
    region: str,
    month: int,
    goal: str,
    pregnant: bool,
    lactating: bool,
) -> None:
    t = calculate_water_target(
        weight_kg=weight,
        kcal_daily=kcal,
        activity=activity,
        region=region,
        month=month,
        goal=goal,
        conditions=frozenset(),
        pregnant=pregnant,
        lactating=lactating,
    )
    assert int(SAFETY_MIN_ML) <= t.total_ml <= int(SAFETY_MAX_ML)


@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
@given(
    weight=_weight_strat,
    kcal=_kcal_strat,
    activity=_activity_strat,
    region=_region_strat,
    month=_month_strat,
    goal=_goal_strat,
    condition=st.sampled_from(["ckd", "heart_failure"]),
)
def test_medical_override_always_caps_at_1500(
    weight: Decimal,
    kcal: int,
    activity: str,
    region: str,
    month: int,
    goal: str,
    condition: str,
) -> None:
    t = calculate_water_target(
        weight_kg=weight,
        kcal_daily=kcal,
        activity=activity,
        region=region,
        month=month,
        goal=goal,
        conditions=frozenset({condition}),
    )
    assert t.total_ml <= int(MEDICAL_OVERRIDE_CAP_ML)
    assert t.capped_by_medical is True


@settings(max_examples=200)
@given(
    weight=_weight_strat,
    kcal=_kcal_strat,
    activity=_activity_strat,
    goal=_goal_strat,
)
def test_deterministic(weight: Decimal, kcal: int, activity: str, goal: str) -> None:
    kwargs = dict(
        weight_kg=weight,
        kcal_daily=kcal,
        activity=activity,
        region="latam",
        month=3,
        goal=goal,
        conditions=frozenset(),
    )
    a = calculate_water_target(**kwargs)  # type: ignore[arg-type]
    b = calculate_water_target(**kwargs)  # type: ignore[arg-type]
    assert a == b


@settings(max_examples=200)
@given(
    w1=st.decimals(min_value=Decimal("40"), max_value=Decimal("80"), places=2),
    delta=st.decimals(min_value=Decimal("1"), max_value=Decimal("50"), places=2),
)
def test_monotonic_in_weight(w1: Decimal, delta: Decimal) -> None:
    """Increasing weight (holding other inputs constant) never decreases total_ml."""
    w2 = w1 + delta
    common = dict(
        kcal_daily=2000,
        activity="sedentary",
        region="eu",
        month=6,
        goal="maintain",
        conditions=frozenset(),
    )
    t1 = calculate_water_target(weight_kg=w1, **common)  # type: ignore[arg-type]
    t2 = calculate_water_target(weight_kg=w2, **common)  # type: ignore[arg-type]
    assert t1.total_ml <= t2.total_ml


@settings(max_examples=200)
@given(
    k1=st.integers(min_value=2000, max_value=4500),
    delta=st.integers(min_value=1, max_value=500),
)
def test_monotonic_in_kcal_above_baseline(k1: int, delta: int) -> None:
    """Above the 2000 baseline, more kcal ⇒ never less water."""
    k2 = k1 + delta
    common = dict(
        weight_kg=Decimal("60"),
        activity="sedentary",
        region="eu",
        month=6,
        goal="maintain",
        conditions=frozenset(),
    )
    t1 = calculate_water_target(kcal_daily=k1, **common)  # type: ignore[arg-type]
    t2 = calculate_water_target(kcal_daily=k2, **common)  # type: ignore[arg-type]
    assert t1.total_ml <= t2.total_ml
