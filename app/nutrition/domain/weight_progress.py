"""Weight progress engine — OLS slope on 14-day weight series.

Answers the user's core question: "Am I losing weight as planned?"

Uses the same robust statistics already in `recalibration.py` (winsorisation +
MAD filter + OLS slope) but as a READ-ONLY operation — no TDEE recalibration,
no cooldown check. Safe to call on every `GET /me/weight-progress`.

Sources:
  - Wishnofsky (1958) 7700 kcal/kg — energy balance constant.
  - Hall (2008) Int J Obes 32:573 — slope reliability requires ≥14-day window.
  - Müller (2016) Curr Opin Clin Nutr Metab Care 19:329 — noise floor weight series.
  - WHO/CDC/AHA: 0.5 kg/week moderate rate for sustainable loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from app.core.logging import get_logger
from app.nutrition.domain.ideal_weight import DEFAULT_WEEKLY_RATE
from app.nutrition.domain.recalibration import (
    MIN_WEIGHT_POINTS,
    _mad_filter,
    _ols_slope,
    _winsorise,
)

_log = get_logger("nutrition.weight_progress")

# ── Constants ────────────────────────────────────────────────────────────────

_LOSING_THRESHOLD_KG_WEEK: Final = Decimal("0.05")   # below this = plateau
_ON_TRACK_RATIO_LOW: Final = Decimal("0.70")          # ≥70% of target rate = on_track
_ON_TRACK_RATIO_HIGH: Final = Decimal("1.40")         # ≤140% of target rate = on_track (not too fast)

# ── Types ─────────────────────────────────────────────────────────────────────

TrendLabel = Literal["losing", "gaining", "plateau", "insufficient_data"]
VsPlan = Literal["on_track", "ahead", "behind", "maintain", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class WeightProgress:
    """Read-only weight trend for a user's last 14 days.

    All callers: use `compute_weight_progress` — never construct directly.
    """

    slope_kg_per_week: Decimal | None   # None when insufficient_data
    trend_label: str                     # TrendLabel
    weight_points: int                   # number of weigh-in entries used
    days_tracked_last_14: int            # total days with a weight log in window
    projected_goal_date: date | None     # None when no clear target or too few points
    vs_plan: str                         # VsPlan


# ── Public function ──────────────────────────────────────────────────────────

def compute_weight_progress(
    *,
    weights: list[tuple[int, float]],    # (day_index, weight_kg)
    weight_to_lose_kg: Decimal | None,   # from WeightInsights; None if already healthy
    goal: str,
    target_weekly_rate_kg: Decimal = DEFAULT_WEEKLY_RATE,
    today: date | None = None,
) -> WeightProgress:
    """Compute weight trend from a 14-day weigh-in series.

    Args:
        weights: List of (day_index, weight_kg). day_index from utc_day_index().
        weight_to_lose_kg: kg remaining to ideal weight (from WeightInsights).
                           None when user is already in healthy range.
        goal: User goal string (e.g. "weight_loss", "weight_maintenance").
        target_weekly_rate_kg: Target loss rate. Default 0.5 kg/week (moderate).
        today: Reference date. Defaults to date.today().
    """
    _today = today or date.today()
    days_tracked = len(set(idx for idx, _ in weights))

    if len(weights) < MIN_WEIGHT_POINTS:
        return WeightProgress(
            slope_kg_per_week=None,
            trend_label="insufficient_data",
            weight_points=len(weights),
            days_tracked_last_14=days_tracked,
            projected_goal_date=None,
            vs_plan="insufficient_data",
        )

    # Robust pre-treatment: winsorise extremes, MAD-filter outliers
    weights_only = [w for _, w in weights]
    winsorised = _winsorise(weights_only)
    series = list(zip([d for d, _ in weights], winsorised, strict=True))
    series = _mad_filter(series)

    if len(series) < MIN_WEIGHT_POINTS:
        return WeightProgress(
            slope_kg_per_week=None,
            trend_label="insufficient_data",
            weight_points=len(series),
            days_tracked_last_14=days_tracked,
            projected_goal_date=None,
            vs_plan="insufficient_data",
        )

    slope_day = _ols_slope(series)                      # kg/day
    slope_week = Decimal(str(slope_day * 7)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    trend_label = _classify_trend(slope_week)
    vs_plan = _classify_vs_plan(
        slope_week=slope_week,
        goal=goal,
        target_weekly_rate_kg=target_weekly_rate_kg,
    )

    # Projected date: only meaningful when actively losing weight to a goal
    projected_date: date | None = None
    if (
        slope_day < -1e-6
        and weight_to_lose_kg is not None
        and weight_to_lose_kg > 0
    ):
        days_to_goal = int(float(weight_to_lose_kg) / abs(slope_day))
        if 0 < days_to_goal < 3650:  # cap at 10 years for sanity
            projected_date = _today + timedelta(days=days_to_goal)

    return WeightProgress(
        slope_kg_per_week=slope_week,
        trend_label=trend_label,
        weight_points=len(series),
        days_tracked_last_14=days_tracked,
        projected_goal_date=projected_date,
        vs_plan=vs_plan,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _classify_trend(slope_week: Decimal) -> TrendLabel:
    if slope_week < -_LOSING_THRESHOLD_KG_WEEK:
        return "losing"
    if slope_week > _LOSING_THRESHOLD_KG_WEEK:
        return "gaining"
    return "plateau"


def _classify_vs_plan(
    *,
    slope_week: Decimal,
    goal: str,
    target_weekly_rate_kg: Decimal,
) -> VsPlan:
    if goal in ("weight_maintenance", "maintain"):
        return "maintain"
    if goal in ("muscle_gain", "weight_gain"):
        # For gain goals, positive slope = on_track
        if slope_week >= target_weekly_rate_kg * _ON_TRACK_RATIO_LOW:
            return "on_track"
        return "behind"

    # Weight-loss goal (and any unknown goal string — treat conservatively as loss)
    if goal not in ("weight_loss", "lose_weight"):
        _log.warning("classify_vs_plan_unknown_goal", goal=goal)
    # Weight-loss goal: slope should be negative (losing)
    if slope_week >= -_LOSING_THRESHOLD_KG_WEEK:
        # Not losing meaningfully
        return "behind"

    actual_rate = abs(slope_week)
    low = target_weekly_rate_kg * _ON_TRACK_RATIO_LOW   # 0.35 kg/week
    high = target_weekly_rate_kg * _ON_TRACK_RATIO_HIGH  # 0.70 kg/week

    if actual_rate > high:
        return "ahead"
    if actual_rate >= low:
        return "on_track"
    return "behind"
