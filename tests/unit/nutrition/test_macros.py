"""MacroBreakdown property test — must satisfy MACRO_TOLERANCE."""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from app.nutrition.domain.kcal_range import to_range
from app.nutrition.domain.macro_partitioning import compute_macros, is_within_tolerance
from app.shared.domain.value_objects import KCAL_RANGE_WIDTH


@given(
    kcal=st.integers(min_value=1200, max_value=4000),
    w=st.integers(min_value=40, max_value=140),
    goal=st.sampled_from(["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]),
)
def test_macros_satisfy_tolerance(kcal, w, goal):
    m = compute_macros(kcal_target=kcal, weight_kg=Decimal(w), goal=goal)
    assert is_within_tolerance(m, kcal), f"macros {m} derived {m.derived_kcal()} vs target {kcal}"


@given(kcal=st.integers(min_value=1200, max_value=4000))
def test_kcal_range_width_is_200(kcal):
    r = to_range(kcal)
    assert r.max - r.min == KCAL_RANGE_WIDTH
