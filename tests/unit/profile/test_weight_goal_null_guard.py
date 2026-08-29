"""Regression B1 — WeightGoalResponse builds correctly with no weigh-ins."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydValidationError

from app.profile.presentation.schemas import WeightGoalResponse


def _make_empty() -> WeightGoalResponse:
    return WeightGoalResponse(
        current_weight_kg=None,
        goal_weight_kg=None,
        starting_weight_kg=None,
        ideal_weight_kg=None,
        ideal_weight_min_kg=None,
        ideal_weight_max_kg=None,
        bmi=None,
        bmi_category=None,
        obesity_grade=None,
        delta_kg=None,
        lost_so_far_kg=None,
        progress_pct=None,
        weight_loss_milestone=None,
        waist_cm=None,
        last_waist_date=None,
        weekly_projected_kg=None,
        weeks_to_goal=None,
        tdee_kcal=None,
        actual_weekly_kg=None,
        latam_context_note=False,
        trend_label="insufficient_data",
        vs_plan="insufficient_data",
        weight_points_14d=0,
        status="no_data",
        recalibration_suggested=False,
    )


def test_weight_goal_response_builds_with_no_weigh_ins():
    """No weigh-ins → all optional fields None, status=no_data. Must not raise."""
    r = _make_empty()
    assert r.status == "no_data"
    assert r.weight_points_14d == 0
    assert r.trend_label == "insufficient_data"
    assert r.actual_weekly_kg is None
    assert r.recalibration_suggested is False


def test_weight_goal_response_builds_with_full_data():
    r = WeightGoalResponse(
        current_weight_kg=78.5,
        goal_weight_kg=70.0,
        starting_weight_kg=85.0,
        ideal_weight_kg=72.0,
        ideal_weight_min_kg=65.0,
        ideal_weight_max_kg=79.0,
        bmi=25.3,
        bmi_category="overweight",
        obesity_grade=None,
        delta_kg=-8.5,
        lost_so_far_kg=6.5,
        progress_pct=49.2,
        weight_loss_milestone="5%",
        waist_cm=88.0,
        last_waist_date="2026-08-20",
        weekly_projected_kg=-0.45,
        weeks_to_goal=19,
        tdee_kcal=2100,
        actual_weekly_kg=-0.38,
        latam_context_note=True,
        trend_label="losing",
        vs_plan="on_track",
        weight_points_14d=8,
        status="on_track",
        recalibration_suggested=False,
    )
    assert r.bmi == 25.3
    assert r.weight_points_14d == 8
    assert r.status == "on_track"


def test_weight_goal_response_rejects_extra_fields():
    with pytest.raises(PydValidationError):
        WeightGoalResponse(
            **_make_empty().model_dump(),
            unexpected_field="x",  # type: ignore[call-arg]
        )
