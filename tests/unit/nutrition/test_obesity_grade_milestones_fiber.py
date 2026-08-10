"""QA-A2 — obesity grade, weight loss milestones, fiber 30g floor.

Invariants (per PDF Plan_Perdida_Peso + OMS BMI classification):
  - compute_obesity_grade returns 1/2/3/None based on WHO thresholds
  - weight_loss_milestone is the highest threshold crossed, never skips one
  - fiber_target_g >= 30 for every weight_loss plan, regardless of kcal_target
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.nutrition.domain.ideal_weight import classify_bmi, compute_obesity_grade


# ── Obesity grade ─────────────────────────────────────────────────────────────

class TestComputeObesityGrade:
    """WHO: Obesity I=30–34.9, II=35–39.9, III≥40. None when < 30."""

    @pytest.mark.parametrize("bmi, expected", [
        (Decimal("18.0"), None),
        (Decimal("22.5"), None),
        (Decimal("27.0"), None),
        (Decimal("29.9"), None),
        (Decimal("30.0"), 1),
        (Decimal("34.9"), 1),
        (Decimal("35.0"), 2),
        (Decimal("39.9"), 2),
        (Decimal("40.0"), 3),
        (Decimal("50.0"), 3),
        (Decimal("65.0"), 3),
    ])
    def test_boundaries(self, bmi: Decimal, expected: int | None) -> None:
        assert compute_obesity_grade(bmi) == expected

    def test_none_for_healthy(self) -> None:
        assert compute_obesity_grade(Decimal("23.5")) is None

    def test_none_for_overweight(self) -> None:
        assert compute_obesity_grade(Decimal("28.0")) is None

    def test_grade1_is_never_2_or_3(self) -> None:
        for bmi_int in range(300, 350):  # 30.0–34.9
            bmi = Decimal(bmi_int) / 10
            assert compute_obesity_grade(bmi) == 1

    def test_grade2_is_never_1_or_3(self) -> None:
        for bmi_int in range(350, 400):  # 35.0–39.9
            bmi = Decimal(bmi_int) / 10
            assert compute_obesity_grade(bmi) == 2

    @given(st.decimals(min_value=Decimal("40"), max_value=Decimal("70"), places=1))
    @settings(max_examples=50)
    def test_grade3_for_all_extreme_obesity(self, bmi: Decimal) -> None:
        assert compute_obesity_grade(bmi) == 3

    @given(st.decimals(min_value=Decimal("1"), max_value=Decimal("29.99"), places=2))
    @settings(max_examples=80)
    def test_none_for_all_non_obese(self, bmi: Decimal) -> None:
        assert compute_obesity_grade(bmi) is None

    def test_classify_bmi_still_returns_obese_not_grade(self) -> None:
        """bmi_category backward compat — must stay 'obese', not 'obese_1'."""
        assert classify_bmi(Decimal("36.7")) == "obese"
        assert classify_bmi(Decimal("30.0")) == "obese"
        assert classify_bmi(Decimal("42.0")) == "obese"


# ── Milestone calculation (pure logic, extracted from router) ─────────────────

def _compute_milestone(starting: float, current: float) -> str | None:
    """Mirror of router.py milestone logic for weight_loss goal.

    Invariants (fixed 2026-08-09):
    - Returns None when current >= starting (no actual weight loss).
    - Returns None for non-weight_loss goals (see _compute_milestone_for_goal).
    """
    if starting <= 0:
        return None
    lost = starting - current  # signed — negative means weight gain
    if lost <= 0:
        return None
    pct = (lost / starting) * 100
    if pct >= 20:
        return "20%"
    if pct >= 15:
        return "15%"
    if pct >= 10:
        return "10%"
    if pct >= 5:
        return "5%"
    return None


def _compute_milestone_for_goal(goal: str, starting: float, current: float) -> str | None:
    """Mirror of router.py full milestone logic including goal gate."""
    if goal != "weight_loss":
        return None
    return _compute_milestone(starting, current)


class TestWeightLossMilestone:
    @pytest.mark.parametrize("start, current, expected", [
        (100.0, 100.0, None),        # no loss
        (100.0, 96.0,  None),        # 4% — below threshold
        (100.0, 95.0,  "5%"),        # exactly 5%
        (100.0, 94.9,  "5%"),        # 5.1%
        (100.0, 90.0,  "10%"),       # exactly 10%
        (100.0, 89.0,  "10%"),       # 11%
        (100.0, 85.0,  "15%"),       # exactly 15%
        (100.0, 80.0,  "20%"),       # exactly 20%
        (100.0, 75.0,  "20%"),       # 25% — capped at 20% label
        (80.0,  76.0,  "5%"),        # 5% of 80kg = 4kg lost
        (80.0,  72.0,  "10%"),       # 10% of 80kg = 8kg lost
    ])
    def test_milestone_thresholds(self, start: float, current: float, expected: str | None) -> None:
        assert _compute_milestone(start, current) == expected

    def test_milestone_never_skips(self) -> None:
        # A user at 12% loss should be "10%", not "15%"
        assert _compute_milestone(100.0, 88.0) == "10%"

    def test_milestone_none_when_gaining(self) -> None:
        assert _compute_milestone(80.0, 82.0) is None

    def test_milestone_none_for_zero_start(self) -> None:
        assert _compute_milestone(0.0, 0.0) is None

    def test_milestone_none_for_non_weight_loss_goal(self) -> None:
        """Milestone is weight-loss-specific — must be None for all other goals."""
        for non_loss_goal in ("muscle_gain", "weight_gain", "maintain", "health"):
            assert _compute_milestone_for_goal(non_loss_goal, 100.0, 90.0) is None, (
                f"expected None for goal={non_loss_goal}"
            )

    def test_milestone_fires_for_weight_loss_goal(self) -> None:
        """Confirm weight_loss goal + actual loss → milestone."""
        assert _compute_milestone_for_goal("weight_loss", 100.0, 90.0) == "10%"
        assert _compute_milestone_for_goal("weight_loss", 100.0, 95.0) == "5%"
        assert _compute_milestone_for_goal("weight_loss", 100.0, 80.0) == "20%"

    def test_milestone_none_for_weight_loss_goal_but_gaining(self) -> None:
        """weight_loss goal + weight gain (current > starting) → None."""
        assert _compute_milestone_for_goal("weight_loss", 80.0, 85.0) is None

    @given(
        st.floats(min_value=40.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=40.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_milestone_is_always_valid_label_or_none(self, start: float, lost: float) -> None:
        current = start - lost
        result = _compute_milestone(start, current)
        assert result in {None, "5%", "10%", "15%", "20%"}


# ── Fiber 30g floor for weight_loss ──────────────────────────────────────────

class TestFiber30gFloor:
    """For weight_loss goal, fiber_target_g must always be >= 30g."""

    def _fiber_formula(self, kcal_target: int, goal: str) -> int:
        """Mirror of use_cases.py fiber computation."""
        fiber = max(1, int(round(kcal_target / 1000 * 14)))
        if goal == "weight_loss":
            fiber = max(fiber, 30)
        return fiber

    @pytest.mark.parametrize("kcal_target", [1000, 1200, 1500, 1700, 1800, 2000, 2200, 2500])
    def test_weight_loss_always_at_least_30g(self, kcal_target: int) -> None:
        fiber = self._fiber_formula(kcal_target, "weight_loss")
        assert fiber >= 30, f"fiber={fiber} for kcal={kcal_target} with weight_loss goal"

    @pytest.mark.parametrize("kcal_target, goal", [
        (1700, "maintain"),
        (1700, "muscle_gain"),
        (1700, "weight_gain"),
        (1700, "health"),
    ])
    def test_other_goals_use_dga_formula(self, kcal_target: int, goal: str) -> None:
        fiber = self._fiber_formula(kcal_target, goal)
        expected = max(1, int(round(kcal_target / 1000 * 14)))
        assert fiber == expected

    def test_high_kcal_weight_loss_still_uses_dga_if_above_30(self) -> None:
        # 2500 kcal → 14*2.5 = 35g > 30 → floor doesn't restrict
        fiber = self._fiber_formula(2500, "weight_loss")
        assert fiber == 35

    def test_low_kcal_weight_loss_gets_floor(self) -> None:
        # 1200 kcal → 14*1.2 = 16.8 → 17g < 30 → floor kicks in
        fiber = self._fiber_formula(1200, "weight_loss")
        assert fiber == 30

    @given(st.integers(min_value=800, max_value=4000))
    @settings(max_examples=100)
    def test_weight_loss_fiber_floor_property(self, kcal: int) -> None:
        fiber = self._fiber_formula(kcal, "weight_loss")
        assert fiber >= 30
