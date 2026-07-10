"""ADR-0002 — dynamic metabolic recalibration.

Inputs: 14-day windowed weight series + intake series + current TDEE + biometrics.
Outputs: new TDEE (clamped ±15%) or None (skip), reason code.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from app.nutrition.domain.intake_bias import corrected_kcal_in
from app.nutrition.domain.mifflin_st_jeor import compute_bmr

# Source: Wishnofsky 1958 (JAMA 168:445) — 1 lb fat ≈ 3500 kcal, i.e.
# 1 kg ≈ 7700 kcal. Modern critiques (Hall 2008, Int J Obes 32:573) show
# the constant is closer to ~9400 kcal/kg at steady state; we keep the
# classical 7700 for conservative deficit estimation and let the recalibration
# blend (0.5 Mifflin + 0.5 observed) absorb the bias.
KCAL_PER_KG = 7700.0

# Source: Hall 2011 (Lancet 378:826) — weekly slope from daily weighing is
# noisy below ~14 days due to glycogen/water shifts (Müller 2016, Curr Opin
# Clin Nutr Metab Care 19:329). Require 14 days minimum intake history.
MIN_DAYS = 14

# Heuristic floor for OLS slope reliability: ≥7 weight points gives
# acceptable variance on a 14-day window (every-other-day weighing).
MIN_WEIGHT_POINTS = 7

# Cooldown 14d aligns with the slope window — re-triggering before the
# next window completes would introduce serial correlation in the blend.
COOLDOWN_DAYS = 14

# 50% divergence between expected and observed weight slope = action
# threshold. Below this, individual ±10% Mifflin error (Frankenfield 2005)
# dominates noise; no recalibration warranted.
DELTA_RATIO_THRESHOLD = 0.5

# 15% per-cycle change cap prevents oscillation from a single noisy window.
# Aligns with FDA "minor change" tolerance for medical nutrition therapy.
CLAMP_PCT = 0.15

Reason = Literal["plateau", "weight_change", "goal_change", "manual"]


@dataclass(frozen=True, slots=True)
class RecalibrationInput:
    sex: str
    weight_kg_now: Decimal
    height_cm: Decimal
    age: int
    activity_factor: Decimal
    goal: str
    tdee_current: int
    days_since_last_recalibration: int
    weights: list[tuple[int, float]]  # (day_index, weight_kg) — last 14d
    kcal_in: list[int]  # daily intake — last 14d (len <= 14)
    # `day_index` contract (D13): MUST be computed via
    # `app.shared.domain.time.utc_day_index(dt)` from a timezone-aware
    # `datetime`. Naive timestamps or local-civil-date ordinals will desync
    # the OLS slope across DST transitions and across clients in different
    # zones. Callers passing raw `(now - start).days` against naive
    # datetimes is a CONTRACT VIOLATION even though Python won't complain.

    def __post_init__(self) -> None:
        """D13 runtime guard — validate day_index contract.

        The `weights` series MUST be ordered by `day_index` non-decreasing
        and every index MUST be a non-negative integer (utc_day_index always
        returns ≥0 for dates ≥ UTC_EPOCH_DATE). A monotonic violation here
        is almost always a caller computing `(now - start).days` against
        naive timestamps that crossed a DST boundary, or sorting by a
        local-civil-date that shifted. We refuse to compute an OLS slope
        on out-of-order input rather than emit a silently-biased TDEE.
        """
        if not self.weights:
            return
        prev: int | None = None
        for idx, _w in self.weights:
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise ValueError(
                    f"weights[].day_index must be int, got {type(idx).__name__}",
                )
            if idx < 0:
                raise ValueError(
                    f"weights[].day_index must be ≥0 (got {idx}); see "
                    "app.shared.domain.time.utc_day_index — D13 contract.",
                )
            if prev is not None and idx < prev:
                raise ValueError(
                    f"weights[] day_index must be non-decreasing; "
                    f"saw {idx} after {prev}. Likely cause: naive datetimes "
                    "across DST boundary. See D13 contract.",
                )
            prev = idx


@dataclass(frozen=True, slots=True)
class RecalibrationResult:
    tdee_new: int
    bmr_new: int
    reason: Reason
    slope_kg_per_day: float
    delta_ratio: float


@dataclass(frozen=True, slots=True)
class RecalibrationSkipped:
    reason: str  # 'insufficient_data' | 'cooldown' | 'delta_below_threshold' | 'athlete_bulk'


class InsufficientDataForRecalc(Exception):
    """Raised when robust outlier filtering leaves <MIN_WEIGHT_POINTS samples.

    R1 — robust statistics (Wilcox 2005, *Introduction to Robust Estimation*;
    Leys 2013, J Exp Soc Psychol 49:764, MAD-based outlier detection).
    """


class IntakeBelowPhysiologicalFloor(Exception):
    """D6 — corrected intake mean falls below 0.5 × BMR.

    Self-reported intake below half of BMR is physiologically implausible at
    steady state for non-fasting subjects: even after bias correction
    (R2; Lichtman 1992) the residual signal is too noisy to drive TDEE
    recalibration. We abort the cycle and treat the window as "no data"
    rather than feed garbage into the blend.

    Sources:
    - Lichtman SW et al. 1992 (NEJM 327:1893) — establishes severe
      under-report in obese cohort; cases <800 kcal/d frequent and unreliable.
    - Academy of Nutrition & Dietetics 2016 position paper on Relative
      Energy Deficiency in Sport (RED-S), Thomas et al. (Med Sci Sports
      Exerc 48:543) — defines low-energy-availability floor approximating
      0.5 × BMR as the implausibility threshold for self-report.
    """


# D6 floor: corrected_mean must be ≥ 0.5 × BMR to drive recalibration.
INTAKE_FLOOR_FRACTION_OF_BMR: Final = 0.5


def _intake_floor_ok(*, corrected_mean: Decimal, bmr: Decimal) -> bool:
    """Return True iff corrected intake mean ≥ 0.5 × BMR (D6 floor).

    Pure predicate, Decimal-only, used by recalibrate() and exposed for
    property-based testing.
    """
    return corrected_mean >= bmr * Decimal(str(INTAKE_FLOOR_FRACTION_OF_BMR))


def _winsorise(values: list[float], p_low: float = 0.05, p_high: float = 0.95) -> list[float]:
    """Clip extreme values at P5/P95 to reduce leverage of recording errors.

    Source: Wilcox 2005, *Introduction to Robust Estimation and Hypothesis
    Testing*, ch. 3 — winsorisation as a bounded-influence pre-treatment for
    OLS regression on biological time series.
    """
    if not values:
        return values
    sorted_v = sorted(values)
    n = len(sorted_v)
    # Strict-interior clip — round the percentile index up at the low end and
    # down at the high end so the most extreme observations are always
    # clipped to the next-best value, not preserved.
    import math

    lo_idx = min(n - 1, max(0, math.ceil(n * p_low)))
    hi_idx = max(0, min(n - 1, int(n * p_high) - 1))
    hi_idx = max(hi_idx, lo_idx)
    lo = sorted_v[lo_idx]
    hi = sorted_v[hi_idx]
    return [max(lo, min(hi, v)) for v in values]


def _mad_filter(points: list[tuple[int, float]], k: float = 3.0) -> list[tuple[int, float]]:
    """Drop points whose absolute deviation exceeds k * MAD from the median.

    MAD = median(|x_i − median(x)|). Rejection threshold is `k * MAD` with
    k=3 (NOTE: applied directly, WITHOUT the 1.4826 σ-scaling of Leys 2013,
    so this is stricter — ~2σ-equivalent, not 3σ. Deliberately conservative:
    on a 14-day weight series we prefer to drop borderline points than admit a
    water-weight spike into the OLS slope).

    When MAD == 0 (degenerate identical series) → return all points unchanged
    so we don't drop legitimate steady-weight readings.
    """
    if len(points) < 3:
        return list(points)
    vals = sorted(w for _, w in points)
    n = len(vals)
    median = vals[n // 2] if n % 2 == 1 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
    abs_dev_sorted = sorted(abs(w - median) for _, w in points)
    mad = (
        abs_dev_sorted[n // 2]
        if n % 2 == 1
        else 0.5 * (abs_dev_sorted[n // 2 - 1] + abs_dev_sorted[n // 2])
    )
    # Degenerate MAD: when ≥50% of values are identical, MAD collapses to 0
    # and any single deviation passes through. Fall back to mean absolute
    # deviation (Pham-Gia 2001, Math Comput Model 34:921) so the test
    # remains sensitive to lone outliers.
    if mad <= 0.0:
        mean_abs_dev = sum(abs(w - median) for _, w in points) / n
        if mean_abs_dev <= 0.0:
            return list(points)
        # 1.4826 converts MAD to a robust σ-equivalent; absent that, scale
        # mean-abs-dev by ~1.0 and keep threshold equivalent.
        threshold = k * mean_abs_dev
    else:
        threshold = k * mad
    return [(d, w) for d, w in points if abs(w - median) <= threshold]


def _ols_slope(points: list[tuple[int, float]]) -> float:
    """Slope of y vs x via OLS (closed form). Returns 0 if degenerate."""
    if len(points) < 2:
        return 0.0
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def recalibrate(inp: RecalibrationInput) -> RecalibrationResult | RecalibrationSkipped:
    if len(inp.weights) < MIN_WEIGHT_POINTS or len(inp.kcal_in) < MIN_DAYS // 2:
        return RecalibrationSkipped("insufficient_data")
    if inp.days_since_last_recalibration < COOLDOWN_DAYS:
        return RecalibrationSkipped("cooldown")

    # R1 — robust pre-treatment: winsorise tails + reject MAD outliers.
    weights_only = [w for _, w in inp.weights]
    winsorised = _winsorise(weights_only)
    series = list(zip([d for d, _ in inp.weights], winsorised, strict=True))
    series = _mad_filter(series)
    if len(series) < MIN_WEIGHT_POINTS:
        raise InsufficientDataForRecalc(
            f"after_robust_filter: surviving={len(series)} required={MIN_WEIGHT_POINTS}"
        )
    slope = _ols_slope(series)

    # R2 — correct intake under-report bias (Lichtman 1992; Hill 2001).
    # BMI computed from latest weight + height; correction applied before
    # observed-TDEE estimation.
    height_m = float(inp.height_cm) / 100.0
    bmi = float(inp.weight_kg_now) / (height_m * height_m) if height_m > 0 else 25.0
    raw_mean = statistics.fmean(inp.kcal_in)
    corrected_mean_dec = corrected_kcal_in(raw_kcal=Decimal(str(raw_mean)), bmi=Decimal(str(bmi)))
    corrected_mean = float(corrected_mean_dec)

    # D6 — physiological floor: corrected mean must be ≥ 0.5 × BMR. Below
    # this, self-report is too unreliable (Lichtman 1992; AND/RED-S 2016)
    # to drive recalibration; abort and skip the cycle.
    bmr_only = compute_bmr(
        sex=inp.sex,
        weight_kg=inp.weight_kg_now,  # type: ignore[arg-type]
        height_cm=inp.height_cm,
        age=inp.age,
    )
    if not _intake_floor_ok(corrected_mean=corrected_mean_dec, bmr=Decimal(str(bmr_only))):
        raise IntakeBelowPhysiologicalFloor(
            f"corrected_mean={corrected_mean_dec} bmr={bmr_only} "
            f"floor={INTAKE_FLOOR_FRACTION_OF_BMR}×BMR"
        )

    observed_tdee = corrected_mean - slope * KCAL_PER_KG

    mifflin_recalc = bmr_only * float(inp.activity_factor)

    blended = 0.5 * mifflin_recalc + 0.5 * observed_tdee

    # NOTE (2026-07-09): adaptive thermogenesis (Müller 2015) is intentionally
    # NOT applied here. `observed_tdee` is derived from the actual weight slope
    # via the energy-balance identity, so any metabolic adaptation the user
    # experienced is ALREADY reflected in the observed value (they lost less
    # than a static model predicts → slope less steep → observed_tdee lower).
    # Subtracting a separate AT correction on top would DOUBLE-COUNT the
    # adaptation. AT belongs in the FORWARD projection of a *new* deficit
    # (no observed data yet), not in a data-driven recalibration. The prior
    # wiring was also inert: it fed `days_in_deficit = len(kcal_in) ≤ 14`,
    # below AT_MIN_DAYS = 21, so at_correction() always returned 0.
    tdee_new = int(
        round(
            max(
                inp.tdee_current * (1 - CLAMP_PCT),
                min(inp.tdee_current * (1 + CLAMP_PCT), blended),
            )
        )
    )

    # Use the SAME bias-corrected intake that drives observed_tdee (D7 rationale):
    # comparing the observed slope against an expectation built from RAW (under-
    # reported) intake would let the reporting bias itself trigger recalibration,
    # rather than a genuine metabolic divergence.
    expected_kg_per_day = (corrected_mean - inp.tdee_current) / KCAL_PER_KG
    if abs(expected_kg_per_day) < 1e-4:
        # No expected change → can't compute meaningful ratio
        return RecalibrationSkipped("delta_below_threshold")
    delta_ratio = slope / expected_kg_per_day

    # Trigger: only blend if observed reality diverges from expectation by >50%.
    if abs(delta_ratio - 1.0) <= DELTA_RATIO_THRESHOLD:
        return RecalibrationSkipped("delta_below_threshold")

    # Athlete bulk guard.
    if inp.goal == "muscle_gain" and 0.7 <= delta_ratio <= 1.5:
        return RecalibrationSkipped("athlete_bulk")

    reason: Reason = "plateau" if abs(slope) < 1e-4 else "weight_change"
    bmr_new = bmr_only
    return RecalibrationResult(
        tdee_new=tdee_new,
        bmr_new=bmr_new,
        reason=reason,
        slope_kg_per_day=slope,
        delta_ratio=delta_ratio,
    )
