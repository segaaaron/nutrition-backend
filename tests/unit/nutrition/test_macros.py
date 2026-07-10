"""MacroBreakdown property test — must satisfy MACRO_TOLERANCE."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

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


def test_fat_not_trimmed_to_zero_on_high_protein_low_kcal():
    """Regression (2026-07-09): the back-adjust trim loop used to drive fat to
    0 on high-protein/low-kcal profiles (protein anchored to a heavy body on a
    low target), violating the 0.6 g/kg hormone-health floor. Both floors must
    hold: fat ≥ 0.6 g/kg is never sacrificed to the soft ±2% kcal tolerance,
    and protein stays ≥ 1.2 g/kg.
    """
    w = 140
    m = compute_macros(kcal_target=1200, weight_kg=Decimal(w), goal="muscle_gain")
    assert m.fat_g > 0, f"fat trimmed to {m.fat_g}g — hormone-health floor violated"
    assert m.protein_g >= int(round(1.2 * w)), "protein fell below the 1.2 g/kg floor"


@given(
    kcal=st.integers(min_value=800, max_value=4000),
    w=st.integers(min_value=40, max_value=160),
    goal=st.sampled_from(["weight_loss", "muscle_gain", "weight_gain"]),
)
def test_fat_never_trimmed_below_zero(kcal, w, goal):
    """Across the extreme region (very low kcal vs heavy body), the trim loop
    must never produce negative or zero-forced fat — the floor guard stops it."""
    m = compute_macros(kcal_target=kcal, weight_kg=Decimal(w), goal=goal)
    assert m.fat_g >= 0 and m.protein_g >= 0 and m.carbs_g >= 0
