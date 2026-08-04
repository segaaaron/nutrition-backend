"""Unit tests for app/nutrition/domain/ideal_weight.py.

Covers:
  - BMI computation and classification (WHO thresholds)
  - WHO ideal-weight range via h² × BMI
  - Peterson (2016) formula — NHANES-validated
  - Devine (1974) reference — None when height < 152.4 cm
  - compute_weight_insights: direction, delta, timeline, pregnancy override
  - LATAM context note (BMI 25.0–27.9 zone)
  - Edge cases: underweight, exactly-in-range, obese, maintenance-goal override
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.nutrition.domain.ideal_weight import (
    DEFAULT_WEEKLY_RATE,
    WEEKLY_RATES,
    WeightInsights,
    classify_bmi,
    compute_bmi,
    compute_devine_reference,
    compute_ideal_weight_range,
    compute_peterson_ideal,
    compute_weight_insights,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _d(s: str) -> Decimal:
    return Decimal(s)


def _insights(
    *,
    weight_kg: str = "80",
    height_cm: str = "170",
    sex: str = "male",
    goal: str = "weight_loss",
    is_pregnant: bool = False,
    weekly_rate_kg: Decimal = DEFAULT_WEEKLY_RATE,
    today: date | None = None,
) -> WeightInsights:
    return compute_weight_insights(
        weight_kg=_d(weight_kg),
        height_cm=_d(height_cm),
        sex=sex,
        goal=goal,
        is_pregnant=is_pregnant,
        weekly_rate_kg=weekly_rate_kg,
        today=today or date(2026, 8, 3),
    )


# ── compute_bmi ───────────────────────────────────────────────────────────────

class TestComputeBmi:
    def test_basic_male(self) -> None:
        # 80 kg, 170 cm → 80 / 1.70² = 27.68... → 27.7
        bmi = compute_bmi(weight_kg=_d("80"), height_cm=_d("170"))
        assert bmi == _d("27.7")

    def test_rounds_half_even(self) -> None:
        # 75 kg, 180 cm → 75 / 3.24 = 23.148... → 23.1
        bmi = compute_bmi(weight_kg=_d("75"), height_cm=_d("180"))
        assert bmi == _d("23.1")

    def test_zero_weight_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_bmi(weight_kg=_d("0"), height_cm=_d("170"))

    def test_negative_height_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_bmi(weight_kg=_d("70"), height_cm=_d("-10"))


# ── classify_bmi ─────────────────────────────────────────────────────────────

class TestClassifyBmi:
    def test_underweight(self) -> None:
        assert classify_bmi(_d("17.9")) == "underweight"

    def test_healthy_lower_bound(self) -> None:
        assert classify_bmi(_d("18.5")) == "healthy"

    def test_healthy_upper_bound(self) -> None:
        assert classify_bmi(_d("24.9")) == "healthy"

    def test_overweight(self) -> None:
        assert classify_bmi(_d("27.5")) == "overweight"

    def test_obese(self) -> None:
        assert classify_bmi(_d("30.0")) == "obese"

    def test_obese_extreme(self) -> None:
        assert classify_bmi(_d("50.0")) == "obese"

    # WHO boundary: obese ≥ 30.0 — 29.91-29.99 must still be "overweight"
    def test_bmi_29_91_is_overweight_not_obese(self) -> None:
        assert classify_bmi(_d("29.91")) == "overweight"

    def test_bmi_29_99_is_overweight_not_obese(self) -> None:
        assert classify_bmi(_d("29.99")) == "overweight"

    def test_bmi_exactly_30_is_obese(self) -> None:
        assert classify_bmi(_d("30.0")) == "obese"

    def test_bmi_30_01_is_obese(self) -> None:
        assert classify_bmi(_d("30.01")) == "obese"


# ── compute_ideal_weight_range ────────────────────────────────────────────────

class TestIdealWeightRange:
    def test_170cm_range(self) -> None:
        lo, hi = compute_ideal_weight_range(height_cm=_d("170"))
        # 1.7² = 2.89; lo = 2.89 × 18.5 = 53.465 → 53.46; hi = 2.89 × 24.9 = 71.961 → 71.96
        assert lo == _d("53.46")
        assert hi == _d("71.96")

    def test_lo_lt_hi(self) -> None:
        lo, hi = compute_ideal_weight_range(height_cm=_d("165"))
        assert lo < hi

    def test_min_bmi_is_18_5(self) -> None:
        # BMI at lo = weight / h² → should equal 18.5
        lo, _ = compute_ideal_weight_range(height_cm=_d("160"))
        bmi_check = lo / (_d("160") / _d("100")) ** 2
        assert abs(bmi_check - _d("18.5")) < _d("0.02")


# ── compute_peterson_ideal ────────────────────────────────────────────────────

class TestPetersonIdeal:
    def test_170cm(self) -> None:
        # height_m = 1.70
        # IBW = 2.2×22 + 3.5×22×(1.70−1.5) = 48.4 + 15.4 = 63.8
        result = compute_peterson_ideal(height_cm=_d("170"))
        assert result == _d("63.80")

    def test_160cm(self) -> None:
        # height_m = 1.60
        # IBW = 2.2×22 + 3.5×22×(1.60−1.5) = 48.4 + 7.7 = 56.1
        result = compute_peterson_ideal(height_cm=_d("160"))
        assert result == _d("56.10")

    def test_falls_in_who_range(self) -> None:
        lo, hi = compute_ideal_weight_range(height_cm=_d("170"))
        peterson = compute_peterson_ideal(height_cm=_d("170"))
        assert lo <= peterson <= hi

    @given(st.decimals(min_value=Decimal("145"), max_value=Decimal("215"), places=1))
    @settings(max_examples=50)
    def test_always_in_who_range(self, height_cm: Decimal) -> None:
        lo, hi = compute_ideal_weight_range(height_cm=height_cm)
        peterson = compute_peterson_ideal(height_cm=height_cm)
        assert lo <= peterson <= hi


# ── compute_devine_reference ──────────────────────────────────────────────────

class TestDevineReference:
    def test_male_exactly_5feet(self) -> None:
        # 152.4 cm = 5 feet → 0 inches over → 50.0 kg
        result = compute_devine_reference(height_cm=_d("152.4"), sex="male")
        assert result == _d("50.00")

    def test_female_exactly_5feet(self) -> None:
        result = compute_devine_reference(height_cm=_d("152.4"), sex="female")
        assert result == _d("45.50")

    def test_male_170cm(self) -> None:
        # inches_over = (170 - 152.4) / 2.54 = 17.6/2.54 ≈ 6.929
        # 50 + 2.3×6.929 = 50 + 15.937... ≈ 65.94
        result = compute_devine_reference(height_cm=_d("170"), sex="male")
        assert result is not None
        assert _d("65") < result < _d("67")

    def test_below_152_4_returns_none(self) -> None:
        result = compute_devine_reference(height_cm=_d("150"), sex="female")
        assert result is None

    def test_male_gt_female_same_height(self) -> None:
        male = compute_devine_reference(height_cm=_d("170"), sex="male")
        female = compute_devine_reference(height_cm=_d("170"), sex="female")
        assert male is not None and female is not None
        # Devine male base (50) > female base (45.5)
        assert male > female


# ── compute_weight_insights — direction ──────────────────────────────────────

class TestWeightInsightsDirection:
    def test_overweight_direction_lose(self) -> None:
        wi = _insights(weight_kg="90", height_cm="170")  # BMI 31.1 → obese
        assert wi.weight_gap_direction == "lose"

    def test_underweight_direction_gain(self) -> None:
        wi = _insights(weight_kg="45", height_cm="170", goal="muscle_gain")  # BMI 15.6
        assert wi.weight_gap_direction == "gain"

    def test_healthy_direction_maintain(self) -> None:
        wi = _insights(weight_kg="65", height_cm="170")  # BMI 22.5 → healthy
        assert wi.weight_gap_direction == "maintain"

    def test_maintenance_goal_overrides_overweight(self) -> None:
        wi = _insights(weight_kg="90", height_cm="170", goal="weight_maintenance")
        assert wi.weight_gap_direction == "maintain"
        assert wi.weight_to_lose_kg is None


# ── compute_weight_insights — pregnancy override ──────────────────────────────

class TestPregnancyOverride:
    def test_pregnant_direction_always_maintain(self) -> None:
        wi = _insights(weight_kg="95", height_cm="165", is_pregnant=True)
        assert wi.weight_gap_direction == "maintain"

    def test_pregnant_no_timeline(self) -> None:
        wi = _insights(weight_kg="95", height_cm="165", is_pregnant=True)
        assert wi.estimated_weeks is None
        assert wi.estimated_date is None
        assert wi.weight_to_lose_kg is None


# ── compute_weight_insights — timeline ───────────────────────────────────────

class TestTimeline:
    def test_timeline_weeks_at_moderate_rate(self) -> None:
        # 90 kg, 170 cm → needs to lose to reach ~72 kg → delta ≈ 18 kg
        # at 0.5 kg/week → ~36 weeks
        today = date(2026, 8, 3)
        wi = _insights(weight_kg="90", height_cm="170", today=today)
        assert wi.estimated_weeks is not None
        assert wi.estimated_weeks > 0
        assert wi.estimated_date == today + __import__("datetime").timedelta(weeks=wi.estimated_weeks)

    def test_no_timeline_when_healthy(self) -> None:
        wi = _insights(weight_kg="65", height_cm="170")
        assert wi.estimated_weeks is None
        assert wi.estimated_date is None

    def test_slow_rate_more_weeks_than_moderate(self) -> None:
        today = date(2026, 8, 3)
        slow = compute_weight_insights(
            weight_kg=_d("90"), height_cm=_d("170"), sex="male",
            goal="weight_loss", weekly_rate_kg=WEEKLY_RATES["slow"], today=today,
        )
        moderate = compute_weight_insights(
            weight_kg=_d("90"), height_cm=_d("170"), sex="male",
            goal="weight_loss", weekly_rate_kg=WEEKLY_RATES["moderate"], today=today,
        )
        assert slow.estimated_weeks is not None and moderate.estimated_weeks is not None
        assert slow.estimated_weeks > moderate.estimated_weeks


# ── LATAM context note ────────────────────────────────────────────────────────

class TestLatamContextNote:
    def test_bmi_25_triggers_note(self) -> None:
        # 72.3 kg, 170 cm → BMI = 25.0
        wi = _insights(weight_kg="72.3", height_cm="170")
        assert wi.latam_context_note is True

    def test_bmi_below_25_no_note(self) -> None:
        wi = _insights(weight_kg="65", height_cm="170")  # BMI ≈ 22.5
        assert wi.latam_context_note is False

    def test_bmi_above_28_no_note(self) -> None:
        wi = _insights(weight_kg="92", height_cm="170")  # BMI ≈ 31.8
        assert wi.latam_context_note is False


# ── dataclass invariants ──────────────────────────────────────────────────────

class TestDataclassInvariants:
    def test_weight_insights_frozen(self) -> None:
        wi = _insights()
        with pytest.raises(Exception):
            wi.bmi = _d("0")  # type: ignore[misc]

    def test_bmi_category_in_valid_set(self) -> None:
        from app.nutrition.domain.ideal_weight import BMI_CATEGORIES
        wi = _insights()
        assert wi.bmi_category in BMI_CATEGORIES

    def test_rate_label_matches_rate_dict(self) -> None:
        wi = _insights()
        assert wi.weekly_rate_kg == WEEKLY_RATES[wi.weekly_rate_label]

    def test_invalid_weekly_rate_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_weight_insights(
                weight_kg=_d("80"),
                height_cm=_d("170"),
                sex="male",
                goal="weight_loss",
                weekly_rate_kg=_d("0.75"),  # not in WEEKLY_RATES
            )
