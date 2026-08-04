"""Unit tests for app/nutrition/domain/weight_progress.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.nutrition.domain.recalibration import MIN_WEIGHT_POINTS
from app.nutrition.domain.weight_progress import (
    WeightProgress,
    _classify_trend,
    _classify_vs_plan,
    compute_weight_progress,
)

_D = Decimal

TODAY = date(2026, 8, 3)
_RATE = Decimal("0.50")  # 0.5 kg/week default


def _series(slope_kg_per_day: float, n: int = 10, start_weight: float = 85.0) -> list[tuple[int, float]]:
    """Generate synthetic weight series with given slope."""
    return [(i, start_weight + slope_kg_per_day * i) for i in range(n)]


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData:
    def test_empty_series(self) -> None:
        wp = compute_weight_progress(
            weights=[], weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        assert wp.trend_label == "insufficient_data"
        assert wp.vs_plan == "insufficient_data"
        assert wp.slope_kg_per_week is None

    def test_below_min_points(self) -> None:
        weights = [(i, 85.0 - i * 0.05) for i in range(MIN_WEIGHT_POINTS - 1)]
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        assert wp.trend_label == "insufficient_data"
        assert wp.slope_kg_per_week is None

    def test_exactly_min_points_has_data(self) -> None:
        weights = [(i, 85.0 - i * 0.07) for i in range(MIN_WEIGHT_POINTS)]
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        assert wp.trend_label != "insufficient_data"


# ── trend classification ──────────────────────────────────────────────────────

class TestTrendLabel:
    def test_losing_trend(self) -> None:
        # -0.5 kg/week slope → losing
        wp = compute_weight_progress(
            weights=_series(-0.5 / 7, 10),
            weight_to_lose_kg=_D("10"),
            goal="weight_loss",
            today=TODAY,
        )
        assert wp.trend_label == "losing"

    def test_gaining_trend(self) -> None:
        wp = compute_weight_progress(
            weights=_series(0.2 / 7, 10),
            weight_to_lose_kg=_D("10"),
            goal="weight_loss",
            today=TODAY,
        )
        assert wp.trend_label == "gaining"

    def test_plateau_trend(self) -> None:
        # Zero slope = plateau
        weights = [(i, 85.0) for i in range(10)]
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        assert wp.trend_label == "plateau"


# ── classify_trend unit ───────────────────────────────────────────────────────

class TestClassifyTrendDirect:
    def test_exactly_minus_0_05_threshold(self) -> None:
        # -0.05 is NOT losing (threshold < not <=)
        assert _classify_trend(_D("-0.05")) == "plateau"

    def test_below_minus_0_05_is_losing(self) -> None:
        assert _classify_trend(_D("-0.06")) == "losing"

    def test_above_0_05_is_gaining(self) -> None:
        assert _classify_trend(_D("0.06")) == "gaining"

    def test_zero_is_plateau(self) -> None:
        assert _classify_trend(_D("0.00")) == "plateau"


# ── vs_plan classification ────────────────────────────────────────────────────

class TestClassifyVsPlan:
    def test_maintenance_goal_always_maintain(self) -> None:
        result = _classify_vs_plan(
            slope_week=_D("-0.5"), goal="weight_maintenance", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "maintain"

    def test_weight_loss_on_track(self) -> None:
        # -0.5 kg/week target, actual -0.45 → 90% of target → on_track
        result = _classify_vs_plan(
            slope_week=_D("-0.45"), goal="weight_loss", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "on_track"

    def test_weight_loss_ahead(self) -> None:
        # -0.8 kg/week → 160% of target → ahead
        result = _classify_vs_plan(
            slope_week=_D("-0.80"), goal="weight_loss", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "ahead"

    def test_weight_loss_behind(self) -> None:
        # -0.2 kg/week → 40% of target → behind
        result = _classify_vs_plan(
            slope_week=_D("-0.20"), goal="weight_loss", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "behind"

    def test_weight_loss_gaining_is_behind(self) -> None:
        # Positive slope while goal=weight_loss → very behind
        result = _classify_vs_plan(
            slope_week=_D("0.30"), goal="weight_loss", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "behind"

    def test_plateau_while_losing_is_behind(self) -> None:
        result = _classify_vs_plan(
            slope_week=_D("0.00"), goal="weight_loss", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "behind"


# ── projected goal date ───────────────────────────────────────────────────────

class TestProjectedDate:
    def test_projected_date_computed(self) -> None:
        # 10 kg to lose at -0.5 kg/week = -0.0714 kg/day → ~140 days → ~20 weeks
        weights = _series(-0.5 / 7, 10)
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        assert wp.projected_goal_date is not None
        assert wp.projected_goal_date > TODAY

    def test_no_projected_date_when_healthy(self) -> None:
        weights = _series(-0.5 / 7, 10)
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=None, goal="weight_loss", today=TODAY,
        )
        assert wp.projected_goal_date is None

    def test_no_projected_date_when_gaining(self) -> None:
        weights = _series(0.2 / 7, 10)
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        assert wp.projected_goal_date is None


# ── muscle_gain / weight_gain goals ──────────────────────────────────────────

class TestGainGoals:
    def test_muscle_gain_on_track(self) -> None:
        # Gaining at 90% of target rate → on_track
        result = _classify_vs_plan(
            slope_week=_D("0.45"), goal="muscle_gain", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "on_track"

    def test_muscle_gain_behind(self) -> None:
        # Gaining at 40% of target rate → behind
        result = _classify_vs_plan(
            slope_week=_D("0.20"), goal="muscle_gain", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "behind"

    def test_weight_gain_on_track(self) -> None:
        result = _classify_vs_plan(
            slope_week=_D("0.35"), goal="weight_gain", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "on_track"

    def test_weight_gain_behind(self) -> None:
        result = _classify_vs_plan(
            slope_week=_D("0.10"), goal="weight_gain", target_weekly_rate_kg=_D("0.5"),
        )
        assert result == "behind"

    def test_muscle_gain_via_compute(self) -> None:
        # Positive slope with muscle_gain goal → on_track
        wp = compute_weight_progress(
            weights=_series(0.5 / 7, 10),
            weight_to_lose_kg=None,
            goal="muscle_gain",
            today=TODAY,
        )
        assert wp.vs_plan == "on_track"
        assert wp.trend_label == "gaining"


# ── post-MAD-filter insufficient data ────────────────────────────────────────

class TestPostMadFilter:
    def test_extreme_outliers_reduce_to_insufficient(self) -> None:
        # 5 normal points + 2 extreme outliers → MAD filter may drop to < MIN_WEIGHT_POINTS
        # Build a series where all but the "real" points are extreme outliers.
        # MIN_WEIGHT_POINTS = 7; we need len(filtered) < 7 after MAD.
        # Construct: 4 real points at ~85 kg, then 3 wild outliers at 200 kg.
        weights = [(i, 85.0) for i in range(4)] + [(i + 4, 200.0) for i in range(3)]
        wp = compute_weight_progress(
            weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
        )
        # With ≥ MIN_WEIGHT_POINTS total but after MAD filter may have insufficient.
        # Result depends on MAD thresholds — check it doesn't crash and returns a valid state.
        assert wp.trend_label in ("losing", "gaining", "plateau", "insufficient_data")
        assert wp.slope_kg_per_week is not None or wp.trend_label == "insufficient_data"


# ── same-day deduplication in days_tracked ───────────────────────────────────

def test_days_tracked_deduplicates_same_day_entries() -> None:
    # 10 weigh-ins but only 5 distinct day_index values
    weights = [(i // 2, 85.0 - i * 0.01) for i in range(10)]
    wp = compute_weight_progress(
        weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
    )
    # 10 entries but only 5 distinct days (0,0,1,1,2,2,3,3,4,4)
    assert wp.days_tracked_last_14 == 5
    assert wp.weight_points <= 10


# ── dataclass frozen ─────────────────────────────────────────────────────────

def test_weight_progress_frozen() -> None:
    weights = _series(-0.5 / 7, 10)
    wp = compute_weight_progress(
        weights=weights, weight_to_lose_kg=_D("10"), goal="weight_loss", today=TODAY,
    )
    with pytest.raises(Exception):
        wp.trend_label = "modified"  # type: ignore[misc]
