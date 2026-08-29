"""Unit — projected_weekly_kg_actual in WeightInsightsOut.

Verifies that _weight_insights_out() populates the actual projected weekly
rate from the plan's real kcal deficit, distinct from the declared target rate.

Key invariant: when safety caps reduce the deficit below the declared rate,
projected_weekly_kg_actual reflects reality, not the promise.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.nutrition.domain.ideal_weight import (
    DEFAULT_WEEKLY_RATE,
    compute_weight_insights,
)
from app.nutrition.presentation.router import _weight_insights_out


def _wi(
    *,
    weight_kg: str = "75",
    height_cm: str = "165",
    sex: str = "female",
    goal: str = "weight_loss",
):
    return compute_weight_insights(
        weight_kg=Decimal(weight_kg),
        height_cm=Decimal(height_cm),
        sex=sex,
        goal=goal,
        is_pregnant=False,
        weekly_rate_kg=DEFAULT_WEEKLY_RATE,
        today=date(2026, 8, 29),
    )


class TestProjectedWeeklyKgActual:
    def test_deficit_produces_negative_projected_rate(self) -> None:
        """500 kcal/day deficit → actual ≈ −0.45 kg/week (Wishnofsky 7700)."""
        wi = _wi()
        out = _weight_insights_out(wi, kcal_target=1779, tdee=2279)
        assert out is not None
        assert out.projected_weekly_kg_actual is not None
        assert out.projected_weekly_kg_actual < 0

    def test_smaller_deficit_less_than_declared_rate(self) -> None:
        """Safety cap reduces deficit: actual < declared 0.50 kg/week.

        Sedentary woman TDEE=1764, cap=441 kcal → 0.40 kg/week real.
        Declared rate in WeightInsights = 0.50 kg/week.
        """
        wi = _wi()
        out = _weight_insights_out(wi, kcal_target=1323, tdee=1764)
        assert out is not None
        actual = out.projected_weekly_kg_actual
        declared = float(wi.weekly_rate_kg)
        assert actual is not None
        # actual loss must be less than declared (cap constrained it)
        assert abs(actual) < declared

    def test_estimated_weeks_uses_actual_rate(self) -> None:
        """estimated_weeks must reflect the real deficit, not the declared rate.

        Sedentary woman example:
          weight_to_lose_kg = 7.21, projected_actual = −0.4 → 18 weeks
          If using declared 0.5 → 14 weeks (wrong — plan can't deliver that).
        """
        wi = _wi()
        out = _weight_insights_out(wi, kcal_target=1323, tdee=1764)
        assert out is not None
        # Real rate ≈ −0.40 kg/week → more weeks than the declared target
        assert out.estimated_weeks is not None
        # Declared rate gives ~14 weeks; real rate gives ~18. Must be > 14.
        assert out.estimated_weeks > 14

    def test_estimated_weeks_fallback_to_declared_when_no_plan(self) -> None:
        """Without kcal_target/tdee, ETA falls back to declared rate."""
        wi = _wi()
        out_no_plan = _weight_insights_out(wi)
        assert out_no_plan is not None
        # Falls back to the declared-rate ETA from WeightInsights
        assert out_no_plan.estimated_weeks == wi.estimated_weeks

    def test_estimated_date_consistent_with_estimated_weeks(self) -> None:
        """estimated_date must be consistent with estimated_weeks."""
        from datetime import date, timedelta
        wi = _wi()
        out = _weight_insights_out(wi, kcal_target=1323, tdee=1764)
        assert out is not None
        assert out.estimated_date is not None
        assert out.estimated_weeks is not None
        expected = date.today() + timedelta(weeks=out.estimated_weeks)
        assert out.estimated_date == expected

    def test_maintenance_goal_gives_none(self) -> None:
        """Maintenance direction → projected_weekly_kg_actual is None."""
        wi = _wi(goal="weight_maintenance")
        out = _weight_insights_out(wi, kcal_target=2000, tdee=2000)
        assert out is not None
        assert out.projected_weekly_kg_actual is None

    def test_none_wi_returns_none(self) -> None:
        assert _weight_insights_out(None, kcal_target=1800, tdee=2200) is None

    def test_no_goals_gives_none(self) -> None:
        """Without kcal_target/tdee → projected_weekly_kg_actual is None."""
        wi = _wi()
        out = _weight_insights_out(wi)
        assert out is not None
        assert out.projected_weekly_kg_actual is None

    def test_surplus_plan_gives_positive(self) -> None:
        """Underweight user with gain goal → positive projected rate."""
        wi = _wi(weight_kg="45", height_cm="165", goal="weight_gain")
        out = _weight_insights_out(wi, kcal_target=2450, tdee=2200)
        assert out is not None
        assert out.projected_weekly_kg_actual is not None
        assert out.projected_weekly_kg_actual > 0

    def test_projected_matches_weight_projection_domain(self) -> None:
        """Cross-check: router value must equal weight_projection domain output."""
        from app.nutrition.domain.weight_projection import expected_weekly_change

        wi = _wi()
        kcal_target, tdee = 1779, 2279
        out = _weight_insights_out(wi, kcal_target=kcal_target, tdee=tdee)
        expected = float(expected_weekly_change(kcal_target=kcal_target, tdee=tdee).weekly_kg)
        assert out is not None
        assert out.projected_weekly_kg_actual == pytest.approx(expected, abs=1e-6)
