"""Property-based tests for ADR-0015 LiquidCap constraint.

Pure-domain, no DB, no async. ~200 hypothesis examples per property.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.constraints import CONSTRAINTS, LiquidCap
from app.plan.domain.context import (
    DraftPlan,
    MacroTargets,
    MealSlot,
    RecipeView,
    Violation,
)
from app.plan.domain.ports import Constraint


_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_GOALS: tuple[str, ...] = (
    "weight_loss",
    "maintain",
    "muscle_gain",
    "weight_gain",
    "health",
)


def _recipe(meal_format: Literal["solid", "semi_solid", "liquid"]) -> RecipeView:
    return RecipeView(
        id=uuid4(),
        kcal=Decimal("500"),
        protein_g=Decimal("30"),
        carbs_g=Decimal("55"),
        fat_g=Decimal("16"),
        fiber_g=Decimal("8"),
        sodium_mg=400,
        sugar_g=Decimal("5"),
        sat_fat_g=Decimal("3"),
        gi=55,
        tags=(),
        allergens=(),
        meal_time="lunch",
        prep_min=25,
        meal_format=meal_format,
    )


def _targets(goal: str) -> MacroTargets:
    # Cast at boundary: Literal goals validated in MacroTargets.__post_init__.
    return MacroTargets(
        kcal=Decimal("2000"),
        protein_g=Decimal("120"),
        carbs_g=Decimal("220"),
        fat_g=Decimal("66"),
        goal=goal,  # type: ignore[arg-type]
    )


def _plan(formats: list[str], goal: str) -> DraftPlan:
    slots: tuple[MealSlot, ...] = tuple(
        MealSlot(
            slot_index=i,
            meal_time="lunch",
            recipe=_recipe(fmt),  # type: ignore[arg-type]
        )
        for i, fmt in enumerate(formats)
    )
    return DraftPlan(meals=slots, targets=_targets(goal))


# Hypothesis strategies
_format_st = st.sampled_from(["solid", "semi_solid", "liquid"])
_formats_st = st.lists(_format_st, min_size=0, max_size=6)
_goal_st = st.sampled_from(list(_GOALS))


def _count_liquid(formats: list[str]) -> int:
    return sum(1 for f in formats if f == "liquid")


def _max_for(goal: str) -> int:
    return 1 if goal == "weight_loss" else 2


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@_SETTINGS
@given(formats=_formats_st, goal=_goal_st)
def test_liquid_cap_in_bounds(formats: list[str], goal: str) -> None:
    """Violations always non-negative magnitude."""
    cap = LiquidCap()
    violations = cap.check(_plan(formats, goal))
    for v in violations:
        assert v.magnitude >= Decimal("0")


@_SETTINGS
@given(formats=_formats_st)
def test_liquid_cap_weight_loss_one_max(formats: list[str]) -> None:
    """weight_loss with >1 liquid → exactly one violation reported."""
    if _count_liquid(formats) <= 1:
        return
    cap = LiquidCap()
    violations = cap.check(_plan(formats, "weight_loss"))
    assert len(violations) == 1
    assert violations[0].constraint == "liquid_cap"


@_SETTINGS
@given(formats=_formats_st, goal=st.sampled_from(
    ["maintain", "muscle_gain", "weight_gain", "health"]
))
def test_liquid_cap_maintain_two_max(formats: list[str], goal: str) -> None:
    """Non-weight-loss goals with >2 liquid → one violation."""
    if _count_liquid(formats) <= 2:
        return
    cap = LiquidCap()
    violations = cap.check(_plan(formats, goal))
    assert len(violations) == 1


@_SETTINGS
@given(
    formats=st.lists(
        st.sampled_from(["solid", "semi_solid"]), min_size=0, max_size=6
    ),
    goal=_goal_st,
)
def test_liquid_cap_zero_liquid_passes(
    formats: list[str], goal: str
) -> None:
    """No liquid meals → never violates regardless of goal."""
    cap = LiquidCap()
    assert cap.check(_plan(formats, goal)) == []


@_SETTINGS
@given(formats=_formats_st, goal=_goal_st)
def test_liquid_cap_policy_consistent(
    formats: list[str], goal: str
) -> None:
    """Same plan + goal twice → identical violations (pure function)."""
    cap = LiquidCap()
    plan = _plan(formats, goal)
    assert cap.check(plan) == cap.check(plan)


@_SETTINGS
@given(formats=_formats_st, goal=_goal_st)
def test_liquid_cap_magnitude_equals_excess(
    formats: list[str], goal: str
) -> None:
    """Violation magnitude == n_liquid - max_allowed."""
    n_liquid = _count_liquid(formats)
    max_allowed = _max_for(goal)
    cap = LiquidCap()
    violations = cap.check(_plan(formats, goal))
    if n_liquid > max_allowed:
        assert violations[0].magnitude == Decimal(n_liquid - max_allowed)
    else:
        assert violations == []


@_SETTINGS
@given(
    n_semi_solid=st.integers(min_value=0, max_value=6), goal=_goal_st
)
def test_liquid_cap_not_counting_semi_solid(
    n_semi_solid: int, goal: str
) -> None:
    """semi_solid does NOT count toward the liquid cap."""
    formats = ["semi_solid"] * n_semi_solid
    cap = LiquidCap()
    assert cap.check(_plan(formats, goal)) == []


@_SETTINGS
@given(goal=_goal_st)
def test_liquid_cap_within_cap_passes(goal: str) -> None:
    """Exactly cap-many liquid meals → no violation."""
    cap = LiquidCap()
    formats = ["liquid"] * _max_for(goal)
    assert cap.check(_plan(formats, goal)) == []


def test_liquid_cap_registered_in_registry() -> None:
    """Registry auto-registration covers LiquidCap by name."""
    assert "liquid_cap" in CONSTRAINTS
    assert isinstance(CONSTRAINTS["liquid_cap"], LiquidCap)


def test_liquid_cap_implements_constraint_protocol() -> None:
    """LiquidCap satisfies the Constraint Protocol (structural + callable)."""
    cap = LiquidCap()
    assert isinstance(cap, Constraint)
    assert callable(cap.check)
    # And returns the right type for a trivial empty plan.
    result = cap.check(_plan([], "maintain"))
    assert isinstance(result, list)
    for v in result:
        assert isinstance(v, Violation)
