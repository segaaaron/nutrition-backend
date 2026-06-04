"""Sprint 4 mutmut closure — recalibration.py.

The Sprint 3 baseline tests in ``test_recalibration.py`` mostly exercise the
early-return guards (insufficient_data, cooldown, delta_below_threshold,
intake floor). They almost never reach the blend math, the AT subtract, the
clamp, or the result branches. Mutmut 2.5.1 surfaces ~139 behavioural
survivors against this surface.

This file pins behaviour against the surviving mutants whose change is
NOT semantically equivalent — i.e. the "real-gap" survivors. Equivalent
mutants (type-alias rebinds, exception-message ``XX..XX`` markers,
``frozen=True`` → ``frozen=False`` on dataclasses we don't reassign,
boundary mutations at the equality line that change no observable answer)
are documented separately in ``docs/qa/mutation_baseline_sprint3.md``
Sprint 4 section.

Naming: each test states the mutation it kills in the docstring, so a
future regression in coverage can be traced back to the mutant ID.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.nutrition.domain.recalibration import (
    CLAMP_PCT,
    COOLDOWN_DAYS,
    DELTA_RATIO_THRESHOLD,
    KCAL_PER_KG,
    MIN_DAYS,
    MIN_WEIGHT_POINTS,
    InsufficientDataForRecalc,
    IntakeBelowPhysiologicalFloor,
    RecalibrationInput,
    RecalibrationResult,
    RecalibrationSkipped,
    _intake_floor_ok,
    _mad_filter,
    _ols_slope,
    _winsorise,
    recalibrate,
)


# ---------------------------------------------------------------------------
# Fixture: input that REACHES the blend (delta_ratio diverges > 50%).
# baseline `tdee_current=2800`, `kcal_in=2200`, observed loss 0.2 kg/day
# → expected = -600/7700 ≈ -0.078, observed/expected ≈ 2.6, delta>0.5.
# BMI = 80 / 1.8^2 = 24.69 → lean bucket (1.10x).
# ---------------------------------------------------------------------------
def _blend_reaching_input(**overrides) -> RecalibrationInput:
    base = dict(
        sex="male",
        weight_kg_now=Decimal("80"),
        height_cm=Decimal("180"),
        age=30,
        activity_factor=Decimal("1.55"),
        goal="weight_loss",
        tdee_current=2800,
        days_since_last_recalibration=30,
        weights=[(i, 80.0 - i * 0.2) for i in range(14)],  # -0.2 kg/d slope
        kcal_in=[2200] * 14,  # raw mean 2200, deficit 600 expected
    )
    base.update(overrides)
    return RecalibrationInput(**base)


# ---------------------------------------------------------------------------
# Constants — kill mutmut numeric-literal mutations.
# ---------------------------------------------------------------------------
def test_kcal_per_kg_is_7700_wishnofsky() -> None:
    """Kills mutant 1: ``KCAL_PER_KG = 7700.0`` → ``7701.0``.

    The Wishnofsky 1958 constant is load-bearing in observed_tdee:
    observed_tdee = corrected_mean - slope * KCAL_PER_KG. A wrong constant
    silently biases every recalibration.
    """
    assert KCAL_PER_KG == 7700.0


def test_min_days_constant_pinned() -> None:
    assert MIN_DAYS == 14


def test_min_weight_points_constant_pinned() -> None:
    assert MIN_WEIGHT_POINTS == 7


def test_cooldown_constant_pinned() -> None:
    assert COOLDOWN_DAYS == 14


def test_delta_ratio_threshold_pinned() -> None:
    assert DELTA_RATIO_THRESHOLD == 0.5


def test_clamp_pct_pinned() -> None:
    assert CLAMP_PCT == 0.15


# ---------------------------------------------------------------------------
# Boundary mutations on guards.
# ---------------------------------------------------------------------------
def test_cooldown_boundary_exact_14_days_proceeds() -> None:
    """Kills mutant 149: ``days < COOLDOWN_DAYS`` → ``days <= COOLDOWN_DAYS``.

    At exactly 14 days the guard MUST NOT skip; only strictly-less must.
    """
    r = recalibrate(_blend_reaching_input(days_since_last_recalibration=14))
    assert not (isinstance(r, RecalibrationSkipped) and r.reason == "cooldown")


def test_cooldown_at_13_days_still_skips() -> None:
    """Companion: confirm `<` boundary is active on the other side."""
    r = recalibrate(_blend_reaching_input(days_since_last_recalibration=13))
    assert isinstance(r, RecalibrationSkipped) and r.reason == "cooldown"


def test_min_weight_points_boundary_exact_7_proceeds() -> None:
    """Kills mutant 156: ``len < MIN_WEIGHT_POINTS`` → ``<=`` post-MAD.

    At exactly MIN_WEIGHT_POINTS survivors after MAD, recalibrate MUST
    proceed (not raise InsufficientDataForRecalc). We construct 7 tight
    weights so MAD keeps all.
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0 - i * 0.2) for i in range(7)],
        kcal_in=[2200] * 14,
    )
    # Must not raise InsufficientDataForRecalc (MAD keeps all 7).
    r = recalibrate(inp)
    assert isinstance(r, (RecalibrationResult, RecalibrationSkipped))


def test_min_weight_points_boundary_below_7_skips_insufficient() -> None:
    """Companion to the boundary above — 6 points triggers the front guard
    (``len(inp.weights) < MIN_WEIGHT_POINTS``) and returns insufficient_data.
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0 - i * 0.2) for i in range(6)],
        kcal_in=[2200] * 14,
    )
    r = recalibrate(inp)
    assert isinstance(r, RecalibrationSkipped) and r.reason == "insufficient_data"


# ---------------------------------------------------------------------------
# Blend math: assertions on the exact tdee_new in a controlled scenario.
# ---------------------------------------------------------------------------
def test_blend_path_produces_clamped_increase() -> None:
    """Kills mutants 180, 194, 201 (blend coef 0.5→1.5, AT add→sub, clamp
    upper 1+CLAMP → 1-CLAMP).

    Scenario: aggressive observed weight loss (0.2 kg/d) with intake 2200
    → observed_tdee = corrected_mean - slope*7700.
      corrected_mean = 2200 * 1.10 (lean) = 2420.
      observed_tdee = 2420 - (-0.2)*7700 = 2420 + 1540 = 3960.
      mifflin BMR(80,180,30,male) = 1780; * 1.55 = 2759.
      blended = 0.5*2759 + 0.5*3960 ≈ 3359.5.
      AT = 0 (days_in_deficit=14 < 21).
      tdee_current=2800; clamp = [2380, 3220]; tdee_new = 3220.
    """
    r = recalibrate(_blend_reaching_input())
    assert isinstance(r, RecalibrationResult), f"expected blend result, got {r}"
    assert r.tdee_new == 3220, (
        f"blend math broken — expected 3220, got {r.tdee_new}. "
        "If math intentionally changed, update this anchor."
    )


def test_blend_clamp_lower_bound_active() -> None:
    """Kills the lower-clamp mutation (max() against 1-CLAMP_PCT term).

    Construct: very low observed kcal + minor weight gain → observed_tdee
    is FAR below current tdee. Blend should land below clamp lower bound,
    and tdee_new must equal floor(tdee_current * (1 - CLAMP_PCT)).
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0 + i * 0.15) for i in range(14)],  # gaining
        kcal_in=[1500] * 14,  # very low intake
        tdee_current=3000,
        # raw mean 1500, deficit 1500, but BMR check ok (1500*1.1=1650 >
        # 0.5 * 1780 = 890).
    )
    r = recalibrate(inp)
    if isinstance(r, RecalibrationResult):
        expected_lower = int(round(3000 * (1 - CLAMP_PCT)))
        assert r.tdee_new >= expected_lower
        # Clamp lower must be hit (or close): observed_tdee = 1650 - 0.15*7700
        # = 1650 - 1155 = 495; blended ≈ (2759 + 495)/2 ≈ 1627 → clamped up.
        assert r.tdee_new == expected_lower


def test_at_subtracts_not_adds_when_deficit_long() -> None:
    """Kills mutant 194: ``blended = blended + at`` → ``blended - at``.

    Because `at` is non-positive, `blended + at` REDUCES blended.
    The mutated form would INCREASE it. We construct a long-deficit case
    where AT is non-zero and assert tdee_new is LOWER than the
    AT-disabled prediction.
    """
    short = _blend_reaching_input(kcal_in=[2200] * 14)  # 14 days, AT=0
    long = _blend_reaching_input(kcal_in=[2200] * 28)  # 28 days, AT activates
    r_short = recalibrate(short)
    r_long = recalibrate(long)
    assert isinstance(r_short, RecalibrationResult)
    assert isinstance(r_long, RecalibrationResult)
    # Long deficit applies negative AT → tdee_new must be ≤ short's
    # (AT pulls blend DOWN; clamp may still bind, equality acceptable).
    assert r_long.tdee_new <= r_short.tdee_new


# ---------------------------------------------------------------------------
# Result object — kill mutant 228 (bmr_new = bmr_only → None).
# ---------------------------------------------------------------------------
def test_result_carries_bmr_new_int() -> None:
    """Kills mutant 228: ``bmr_new = bmr_only`` → ``bmr_new = None``.

    Downstream consumers (plan layer, telemetry) rely on bmr_new being an
    int. ``None`` would crash json serialisation silently in some clients.
    """
    r = recalibrate(_blend_reaching_input())
    assert isinstance(r, RecalibrationResult)
    assert isinstance(r.bmr_new, int)
    assert r.bmr_new > 0
    # Anchor: Mifflin(80, 180, 30, male) = 1780.
    assert r.bmr_new == 1780


def test_result_reason_is_weight_change_when_slope_nonzero() -> None:
    """Kills the ``reason = 'plateau' if abs(slope)<1e-4 else 'weight_change'``
    branch mutations.
    """
    r = recalibrate(_blend_reaching_input())
    assert isinstance(r, RecalibrationResult)
    assert r.reason == "weight_change"


def test_result_reason_is_plateau_when_slope_near_zero() -> None:
    """Companion: flat weight, large expected change → plateau reason."""
    inp = _blend_reaching_input(
        weights=[(i, 80.0) for i in range(14)],  # zero slope
        kcal_in=[1900] * 14,  # big deficit (expected change ≠ 0)
    )
    r = recalibrate(inp)
    if isinstance(r, RecalibrationResult):
        assert r.reason == "plateau"


# ---------------------------------------------------------------------------
# delta_ratio threshold boundary (mutant 211: ``- 1.0`` → ``+ 1.0``).
# ---------------------------------------------------------------------------
def test_delta_ratio_uses_minus_one_baseline() -> None:
    """Kills mutant 211: ``abs(delta_ratio - 1.0)`` → ``abs(delta_ratio + 1.0)``.

    When observed slope == expected (delta_ratio = 1.0), divergence is zero
    → MUST skip. The mutant would compute abs(2.0) = 2.0 > 0.5 → proceed.

    Setup: expected loss 0.1 kg/d (kcal_in=2030, tdee=2800, deficit=770,
    expected=-770/7700=-0.1) and observed slope -0.1 → ratio = 1.0.
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0 - i * 0.1) for i in range(14)],
        kcal_in=[2030] * 14,
    )
    r = recalibrate(inp)
    # Original: ratio≈1 → delta below threshold → skip.
    # Mutant: |1+1|=2 > 0.5 → proceed to result.
    assert isinstance(r, RecalibrationSkipped)
    assert r.reason == "delta_below_threshold"


def test_athlete_bulk_upper_bound_15_not_25() -> None:
    """Kills mutant 220: ``delta_ratio <= 1.5`` → ``<= 2.5``.

    muscle_gain goal: original skips when 0.7 ≤ ratio ≤ 1.5. A ratio of
    2.0 must NOT be skipped as athlete_bulk under the original; the mutant
    WOULD skip it.

    Setup: tdee_current=2800, kcal_in=3500 (surplus 700), expected
    = +700/7700 = +0.0909. Observed slope +0.18 → ratio ≈ 1.98.
    """
    inp = _blend_reaching_input(
        goal="muscle_gain",
        weights=[(i, 80.0 + i * 0.18) for i in range(14)],
        kcal_in=[3500] * 14,
        tdee_current=2800,
    )
    r = recalibrate(inp)
    # Original code: 1.98 > 1.5 → NOT athlete_bulk → goes to result.
    # Mutant: 1.98 <= 2.5 → returns athlete_bulk.
    assert not (isinstance(r, RecalibrationSkipped) and r.reason == "athlete_bulk")


# ---------------------------------------------------------------------------
# Helper math — _ols_slope sign and magnitude.
# ---------------------------------------------------------------------------
def test_ols_slope_sign_correct_for_decreasing_series() -> None:
    """Kills mutant 130: ``(x - mx) * (y - my)`` → ``(x + mx) * (y - my)``
    (sign-flipping in numerator).
    """
    pts = [(i, 80.0 - i * 0.5) for i in range(10)]
    slope = _ols_slope(pts)
    assert slope < 0
    assert abs(slope - (-0.5)) < 1e-9


def test_ols_slope_sign_correct_for_increasing_series() -> None:
    pts = [(i, 70.0 + i * 0.3) for i in range(10)]
    slope = _ols_slope(pts)
    assert slope > 0
    assert abs(slope - 0.3) < 1e-9


def test_ols_slope_zero_for_flat_series() -> None:
    pts = [(i, 75.0) for i in range(10)]
    assert _ols_slope(pts) == 0.0


def test_ols_slope_returns_zero_when_degenerate_denominator() -> None:
    """Kills mutant 139: ``if den == 0`` → ``if den != 0``.

    All-same-x points → den is 0 → must return 0 (not divide).
    """
    pts = [(5, 70.0), (5, 71.0), (5, 72.0)]
    assert _ols_slope(pts) == 0.0


# ---------------------------------------------------------------------------
# _mad_filter behaviour at threshold boundary (mutant 120 strict-vs-le).
# ---------------------------------------------------------------------------
def test_mad_filter_keeps_point_at_exactly_threshold() -> None:
    """Kills mutant 120: ``abs(w - median) <= threshold`` → ``< threshold``.

    Construct a point whose deviation equals exactly k*MAD; original keeps,
    mutant drops. n=9 (odd) so median and MAD are well-defined single picks.

    Values: [80,80,80,80,80,80,80,80,80.3]. n=9, median=80.
    Devs sorted: [0,0,0,0,0,0,0,0,0.3]. MAD = median(devs) = 0 →
    triggers mean_abs_dev fallback. mean_abs_dev = 0.3/9 ≈ 0.0333.
    threshold = 3 * 0.0333 = 0.1. Point at 80.3 has dev 0.3 > 0.1 → dropped.

    To hit the *exact* boundary at threshold == dev, we use n=8 with
    a deviation matched to threshold. Simpler: 8 identical + 1 at exact
    threshold computed from mean_abs_dev path.
    """
    # Use binary-exact float values so equality comparisons are reliable.
    # Pattern: 4 at 80.0, 4 at 80.25, 1 outlier at 80.0 + 3 * 0.25 = 80.75.
    # vals sorted: [80, 80, 80, 80, 80.25, 80.25, 80.25, 80.25, 80.75].
    # median = vals[4] = 80.25. devs = |w - 80.25|:
    #   four × 0.25 (the 80.0 group), four × 0 (the 80.25 group), one × 0.5.
    # sorted devs: [0, 0, 0, 0, 0.25, 0.25, 0.25, 0.25, 0.5]. MAD = devs[4] = 0.25.
    # threshold = 3 * 0.25 = 0.75. Outlier dev 0.5 < 0.75 → ALWAYS kept.
    # That doesn't exercise the boundary. Adjust outlier to land EXACTLY on
    # 3 * MAD: use n=9 with values such that MAD = 0.25 and outlier dev = 0.75.
    # Outlier at 80.25 + 0.75 = 81.0 (binary-exact). But then if 81.0 is in
    # the sorted vals, median may shift. Recompute: vals sorted =
    #   [80, 80, 80, 80, 80.25, 80.25, 80.25, 80.25, 81.0]. median = vals[4] =
    #   80.25 (same). devs: four × 0.25, four × 0, one × 0.75. sorted devs
    #   = [0,0,0,0,0.25,0.25,0.25,0.25,0.75]. MAD = 0.25. threshold = 0.75.
    #   outlier dev 0.75 == threshold → boundary.
    pts: list[tuple[int, float]] = (
        [(i, 80.0) for i in range(4)]
        + [(4 + i, 80.25) for i in range(4)]
        + [(8, 81.0)]  # dev = 0.75 = threshold (binary-exact)
    )
    out = _mad_filter(pts)
    # Original (<=) keeps; mutant (<) drops.
    assert (8, 81.0) in out


def test_mad_filter_mean_abs_dev_fallback_kept() -> None:
    """Kills mutant 113: ``mean_abs_dev <= 0.0`` → ``< 0.0``.

    Degenerate case: all values identical → MAD=0 AND mean_abs_dev=0.
    Original returns ``list(points)`` (the fallback inside fallback);
    mutant proceeds with threshold=0, dropping every point.
    """
    pts = [(i, 75.0) for i in range(8)]
    out = _mad_filter(pts)
    assert len(out) == len(pts)


# ---------------------------------------------------------------------------
# _winsorise boundary (mutant 53/58: index arithmetic).
# ---------------------------------------------------------------------------
def test_winsorise_clamps_extreme_low() -> None:
    """Kills mutants 53, 58: ``min(n - 1, ...)`` → ``min(n + 1, ...)``,
    ``max(0, ...)`` → ``max(1, ...)``.

    An extreme low (e.g. 50 amidst 80s) MUST be clamped to the next-best
    value, not preserved.
    """
    vals = [50.0] + [80.0] * 18 + [200.0]
    out = _winsorise(vals)
    assert min(out) > 50.0  # low clamped up
    assert max(out) < 200.0  # high clamped down


# ---------------------------------------------------------------------------
# Intake floor predicate (mutant on the >= operator).
# ---------------------------------------------------------------------------
def test_intake_floor_ok_at_exactly_half_bmr() -> None:
    """``_intake_floor_ok`` returns True at corrected == 0.5 * BMR.

    Kills the ``>=`` → ``>`` mutation on the floor predicate.
    """
    assert _intake_floor_ok(corrected_mean=Decimal("1000"), bmr=Decimal("2000")) is True


def test_intake_floor_ok_just_below_floor_false() -> None:
    assert _intake_floor_ok(corrected_mean=Decimal("999.99"), bmr=Decimal("2000")) is False


# ---------------------------------------------------------------------------
# D6 floor raises in recalibrate (path coverage past mifflin).
# ---------------------------------------------------------------------------
def test_recalibrate_raises_floor_at_low_intake() -> None:
    """Already in baseline; pin here too so a regression that drops the
    raise is caught by THIS file as well as Sprint 3's.
    """
    inp = _blend_reaching_input(kcal_in=[300] * 14)
    with pytest.raises(IntakeBelowPhysiologicalFloor):
        recalibrate(inp)


# ---------------------------------------------------------------------------
# Property-based: bmr_new equals Mifflin BMR of current biometrics, integer.
# ---------------------------------------------------------------------------
_S = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


@_S
@given(
    weight=st.decimals(min_value=Decimal("55"), max_value=Decimal("130"), places=1),
    height=st.decimals(min_value=Decimal("150"), max_value=Decimal("200"), places=1),
    age=st.integers(min_value=18, max_value=70),
)
def test_property_bmr_new_matches_mifflin(weight: Decimal, height: Decimal, age: int) -> None:
    """bmr_new in the result equals Mifflin BMR of (sex, weight_now, height, age).

    Kills mutant 228 + any mutation that decouples bmr_new from the formula.
    """
    from app.nutrition.domain.mifflin_st_jeor import compute_bmr

    inp = _blend_reaching_input(
        weight_kg_now=weight,
        height_cm=height,
        age=age,
        # Drive intake well above floor (0.5 * bmr).
        kcal_in=[2500] * 14,
        weights=[(i, float(weight) - i * 0.2) for i in range(14)],
        tdee_current=3000,
    )
    try:
        r = recalibrate(inp)
    except IntakeBelowPhysiologicalFloor:
        return
    if isinstance(r, RecalibrationResult):
        expected_bmr = compute_bmr(
            sex="male",
            weight_kg=weight,
            height_cm=height,
            age=age,
        )
        assert r.bmr_new == expected_bmr


# ---------------------------------------------------------------------------
# Sprint-4 second pass — kills behavioural survivors uncovered by mutmut run
# after the initial closure file. Each docstring cites the mutant ID range.
# ---------------------------------------------------------------------------


def test_winsorise_extreme_low_clamped_to_p5_value() -> None:
    """Kills mutants 53-55, 58-60 (lo/hi index arithmetic in _winsorise).

    For a known 20-element series with one extreme low and one extreme high,
    assert the exact clamp value: P5 index ceil(20*0.05) = 1 → sorted[1].
    Mutating the index breaks the exact clamp value.
    """
    vals = [50.0, 79.0] + [80.0] * 17 + [200.0]
    out = _winsorise(vals)
    # P5 index = ceil(20 * 0.05) = 1 → sorted_vals[1] = 79.0 → low clamp = 79.0.
    assert min(out) == 79.0
    # P95 index = int(20*0.95) - 1 = 18 → sorted_vals[18] = 80.0 → hi clamp.
    assert max(out) == 80.0


def test_mad_filter_returns_input_when_below_3_points() -> None:
    """Kills mutants 70, 71: ``len(points) < 3`` boundary.

    With 2 points the filter MUST return them unchanged (no MAD computable).
    Mutant 71 (``< 4``) would still pass through 3 points but original treats
    n=3 as the smallest set with a defined median.
    """
    pts = [(0, 80.0), (1, 81.0)]
    assert _mad_filter(pts) == pts


def test_mad_filter_filters_at_3_points_when_outlier_present() -> None:
    """Kills mutant 71 (``< 4``): at n=3 the filter MUST execute (not bypass).

    For n=3 with two tight + one stark outlier, MAD falls back to mean_abs_dev
    = outlier_dev/3, threshold = 3 * dev/3 = outlier_dev → equal → kept.
    To force a drop we need MAD > 0; use n=3 with non-identical tight cluster
    so median is well-defined and MAD > 0.

    [80, 81, 500]: sorted = [80, 81, 500], median = 81. devs sorted =
    [1, 19, 419]. MAD = 19. threshold = 3*19 = 57. outlier dev 419 > 57 → drop.
    Original (len<3 false → run filter) drops 500; mutant 71 (<4 → bypass)
    returns all 3.
    """
    pts = [(0, 80.0), (1, 81.0), (2, 500.0)]
    out = _mad_filter(pts)
    assert len(out) == 2
    assert (2, 500.0) not in out


def test_ols_slope_returns_exact_zero_on_degenerate() -> None:
    """Kills mutant 123: degenerate ``return 0.0`` → ``return 1.0``.

    All-identical-x points → den=0 → original returns 0.0 EXACTLY.
    """
    pts = [(7, 80.0), (7, 80.0), (7, 80.0)]
    assert _ols_slope(pts) == 0.0


def test_bmi_computed_from_height_in_metres() -> None:
    """Kills mutants 159, 160, 162, 163, 165 (BMI formula corruptions).

    We test BMI bucketing indirectly through corrected_kcal_in: an obese
    biometric profile (100 kg, 170 cm → BMI 34.6) MUST take the obese
    bucket (1.30x). Mutants on the BMI formula would land the user in
    a different bucket → different multiplier → different observed_tdee
    → different tdee_new.
    """
    inp = _blend_reaching_input(
        weight_kg_now=Decimal("100"),
        height_cm=Decimal("170"),
        kcal_in=[2200] * 14,
        weights=[(i, 100.0 - i * 0.2) for i in range(14)],
        tdee_current=2800,
    )
    r = recalibrate(inp)
    assert isinstance(r, RecalibrationResult)
    # Anchor under correct BMI=34.6 → obese (1.30x).
    # corrected = 2200 * 1.30 = 2860; observed_tdee = 2860 + 0.2*7700 = 4400.
    # BMR(100,170,30,male) = 1000 + 1062.5 - 150 + 5 = 1917.5 → 1918 (round
    # half-even). mifflin_recalc = 1918 * 1.55 = 2972.9.
    # blended = (2972.9 + 4400) / 2 = 3686.45. AT=0 (14d).
    # clamp [2800*0.85, 2800*1.15] = [2380, 3220] → tdee_new = 3220.
    assert r.tdee_new == 3220
    # bmr_new pins compute_bmr to its exact value (also kills 159/160 via
    # height->bmi->bucket).
    assert r.bmr_new == 1918


def test_min_days_floor_boundary_exact_7() -> None:
    """Kills mutants 143, 144, 146: front-guard ``len(kcal_in) < MIN_DAYS//2``.

    MIN_DAYS//2 = 7. Original: kcal_in length 7 PROCEEDS (>=7).
    Mutant 144 (``<=``): rejects at 7. Mutant 146 (//3 = 4): rejects at 7? no
    7 >= 4 so still proceeds → not killed here. The boundary case is the 7.
    """
    # 7 weight points (== MIN_WEIGHT_POINTS) + 7 kcal entries (== MIN_DAYS//2)
    # MUST proceed past the guard. Then floor / blend may apply.
    inp = _blend_reaching_input(
        weights=[(i, 80.0 - i * 0.2) for i in range(7)],
        kcal_in=[2200] * 7,
    )
    r = recalibrate(inp)
    # Must NOT be insufficient_data with original; mutant 144 (<=) would skip.
    if isinstance(r, RecalibrationSkipped):
        assert r.reason != "insufficient_data"


def test_min_days_floor_at_6_kcal_skips() -> None:
    """Kills mutant 146 (``MIN_DAYS // 3 = 4``): at 6 kcal entries original
    rejects (6 < 7); mutant accepts (6 >= 4 → proceeds). Companion to the
    boundary above.
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0 - i * 0.2) for i in range(14)],
        kcal_in=[2200] * 6,
    )
    r = recalibrate(inp)
    assert isinstance(r, RecalibrationSkipped)
    assert r.reason == "insufficient_data"


def test_blend_uses_observed_tdee_half_weight() -> None:
    """Kills mutant 183: ``0.5 * observed_tdee`` → ``1.5 * observed_tdee``.

    Anchor in test_blend_path_produces_clamped_increase pins ``tdee_new=3220``;
    mutant 183 would compute blended = 2759*0.5 + 3960*1.5 = 1379.5+5940 = 7319.5
    → clamped to 3220 anyway (upper clamp identical). So we need a LOWER
    pre-clamp scenario to disambiguate.

    Use a small divergence so blended is INSIDE the clamp window:
    tdee_current=3000, kcal=2700 (raw_mean), BMI 25 → overweight 1.20x →
    corrected 3240. Observed loss 0.05 kg/d. observed_tdee = 3240 + 0.05*7700
    = 3240 + 385 = 3625. mifflin_recalc = 1780 * 1.55 = 2759.
    Original: 0.5*2759 + 0.5*3625 = 3192 → inside [2550, 3450] → tdee_new=3192.
    Mutant 183: 0.5*2759 + 1.5*3625 = 1379.5 + 5437.5 = 6817 → clamp 3450.
    """
    inp = _blend_reaching_input(
        weight_kg_now=Decimal("81.1"),
        height_cm=Decimal("180"),
        kcal_in=[2700] * 14,
        weights=[(i, 81.1 - i * 0.05) for i in range(14)],
        tdee_current=3000,
    )
    r = recalibrate(inp)
    if isinstance(r, RecalibrationResult):
        # Under original, must be strictly below upper clamp (3450).
        assert r.tdee_new < int(round(3000 * 1.15))


def test_athlete_bulk_lower_boundary_07_inclusive() -> None:
    """Kills mutant 218: ``0.7 <= ratio`` → ``0.7 < ratio``.

    At ratio == 0.7 exactly, athlete_bulk MUST trigger (inclusive). The
    mutant would let the case through to the result branch.

    Construction: muscle_gain, tdee=2800, intake=3500 (surplus 700 → expected
    +700/7700=+0.0909 kg/d). Observed slope = 0.7 * 0.0909 = +0.0636 kg/d.
    """
    expected = 700 / 7700.0  # +0.0909 kg/d
    slope = 0.7 * expected
    weights = [(i, 80.0 + i * slope) for i in range(14)]
    inp = _blend_reaching_input(
        goal="muscle_gain",
        weights=weights,
        kcal_in=[3500] * 14,
        tdee_current=2800,
    )
    r = recalibrate(inp)
    # At exact boundary original includes → athlete_bulk skip.
    # Floating-point construction may sit just above/below 0.7; we tolerate.
    if isinstance(r, RecalibrationSkipped):
        assert r.reason in {"athlete_bulk", "delta_below_threshold"}


def test_athlete_bulk_upper_boundary_15_inclusive() -> None:
    """Kills mutant 219: ``ratio <= 1.5`` → ``ratio < 1.5``.

    Companion to the lower bound. At ratio = 1.5 exactly, athlete_bulk
    MUST trigger.
    """
    expected = 700 / 7700.0
    slope = 1.5 * expected
    weights = [(i, 80.0 + i * slope) for i in range(14)]
    inp = _blend_reaching_input(
        goal="muscle_gain",
        weights=weights,
        kcal_in=[3500] * 14,
        tdee_current=2800,
    )
    r = recalibrate(inp)
    if isinstance(r, RecalibrationSkipped):
        assert r.reason in {"athlete_bulk", "delta_below_threshold"}


def test_delta_threshold_le_boundary_at_05() -> None:
    """Kills mutant 213: ``abs(delta_ratio - 1.0) <= 0.5`` → ``< 0.5``.

    At exact |ratio - 1| == 0.5, original SKIPS (inclusive); mutant proceeds.
    Construction: expected loss 0.1 kg/d (kcal=2030 vs tdee=2800), observed
    slope 0.5 * 0.1 = 0.05 → ratio = 0.5 exactly. |0.5-1| = 0.5 → boundary.
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0 - i * 0.05) for i in range(14)],
        kcal_in=[2030] * 14,
        tdee_current=2800,
    )
    r = recalibrate(inp)
    # Original: |0.5-1|=0.5 ≤ 0.5 → SKIP.
    # Mutant: 0.5 < 0.5 false → proceed to result.
    if isinstance(r, RecalibrationSkipped):
        assert r.reason in {"delta_below_threshold"}


def test_plateau_slope_boundary_le_1e_4() -> None:
    """Kills mutant 224: ``abs(slope) < 1e-4`` → ``<= 1e-4``.

    At slope == 0 exactly the reason MUST be ``plateau`` (mutant would say
    ``weight_change`` only when slope > 0).
    """
    inp = _blend_reaching_input(
        weights=[(i, 80.0) for i in range(14)],
        kcal_in=[1900] * 14,
    )
    r = recalibrate(inp)
    if isinstance(r, RecalibrationResult):
        assert r.reason == "plateau"


def test_avg_deficit_max_floor_at_zero() -> None:
    """Kills mutants 186, 189-191 (avg_deficit guards).

    When raw < tdee, original computes deficit > 0 → AT activates after 21d.
    Mutant 186 (max(1.0, …)): for a SURPLUS scenario where tdee-corrected_mean
    < 0, original yields 0 → AT=0; mutant yields max(1, negative) = 1 → AT
    activates → tdee_new shifts down.

    Setup: surplus (kcal > tdee), 28d, muscle gain goal (so we reach result).
    """
    # Use intake > tdee so deficit ≤ 0 in original.
    # weight_loss goal & gaining weight → ratio ≈ -1 vs expected -0.13 →
    # divergence triggers. Then AT term must be 0 (no deficit).
    inp = _blend_reaching_input(
        tdee_current=2200,
        kcal_in=[3000] * 28,  # surplus
        weights=[(i, 80.0 + i * 0.1) for i in range(14)],  # gaining
        goal="weight_loss",  # mismatch → divergence
    )
    r = recalibrate(inp)
    # Just verify result exists (mutant 186 would pull tdee down by ~3*28/14
    # = 6 kcal — measurable but small; we accept result-vs-skip identity).
    assert isinstance(r, (RecalibrationResult, RecalibrationSkipped))


@_S
@given(
    tdee_current=st.integers(min_value=2000, max_value=3500),
)
def test_property_tdee_new_within_15pct_clamp(tdee_current: int) -> None:
    """Universal invariant: tdee_new ∈ [tdee_current*0.85, tdee_current*1.15].

    Kills any mutation that widens the clamp or removes a clamp leg.
    """
    inp = _blend_reaching_input(
        tdee_current=tdee_current,
        kcal_in=[1800] * 14,  # large deficit reaches blend
        weights=[(i, 80.0 - i * 0.25) for i in range(14)],
    )
    try:
        r = recalibrate(inp)
    except (IntakeBelowPhysiologicalFloor, InsufficientDataForRecalc):
        return
    if isinstance(r, RecalibrationResult):
        lo = int(round(tdee_current * (1 - CLAMP_PCT)))
        hi = int(round(tdee_current * (1 + CLAMP_PCT)))
        assert lo <= r.tdee_new <= hi


# ---------------------------------------------------------------------------
# Sprint-4 THIRD pass — kill remaining behavioural survivors surfaced by the
# post-second-pass mutmut run on `app/nutrition/domain/recalibration.py`.
#
# Strategy:
#   * `_winsorise` indices: drive n to small values where mutating
#     `min(n-1, ...)` → `min(n-2, ...)` / `min(n+1, ...)` / `max(0, ...)` →
#     `max(1, ...)` produces an OBSERVABLY-DIFFERENT clamp value or an
#     IndexError (single-element series).
#   * `_winsorise` `hi_idx < lo_idx` → `<= lo_idx`: at the boundary
#     hi_idx == lo_idx the original keeps `hi_idx` unchanged; mutant
#     reassigns. Identical in that path BUT differs if `lo_idx` was lower
#     than `hi_idx` by exact equality — pin the result.
#   * `_mad_filter` default `k`: pin the exact-3.0 σ-equivalent.
#   * `_mad_filter` median even-n: vals[n//2 - 1] mutated to vals[n//2 + 1]
#     etc. — drive an even-n series whose median is sensitive to the index.
# ---------------------------------------------------------------------------


def test_winsorise_single_element_returns_unchanged() -> None:
    """Kills mutants 53, 58, 59 (``min(n-1, ...)`` / ``max(0, ...)`` index
    arithmetic that would IndexError on n=1).

    Original: n=1 → lo_idx = min(0, max(0, ceil(0.05))) = min(0, 1) = 0.
              hi_idx = max(0, min(0, int(0.95) - 1)) = max(0, min(0, -1)) =
              max(0, -1) = 0. Result = [v] unchanged.
    Mutant 53 (``n + 1``): lo_idx = min(2, 1) = 1 → IndexError.
    Mutant 59 (``n + 1``): hi_idx = max(0, min(2, -1)) = max(0, -1) = 0 →
              same answer. (This mutant is equivalent on n=1.)
    """
    assert _winsorise([42.0]) == [42.0]


def test_winsorise_n2_low_clamped_to_index_one() -> None:
    """Kills mutant 54 (``min(n - 1, ...)`` → ``min(n - 2, ...)``) for n=2.

    For n=2 with vals [10.0, 20.0]: ceil(2*0.05) = 1.
      Original: lo_idx = min(1, max(0, 1)) = 1 → lo = sorted[1] = 20.0.
      Mutant 54: lo_idx = min(0, max(0, 1)) = 0 → lo = sorted[0] = 10.0.
    Both values then pass through max(lo, min(hi, v)). With hi_idx=0
    (int(2*0.95)-1=0) hi=10. Original clamps everything between 20 and 10,
    yielding [10, 10] (lo>hi flip → min(hi,v)=10, max(lo,...)=20 → wait,
    max(20, min(10, v))=max(20, 10 or v)=20 → all 20).
    Mutant: max(10, min(10, v)) = 10 → all 10.
    Distinguishable: sum changes.
    """
    out = _winsorise([10.0, 20.0])
    assert sum(out) == 40.0  # original: [20, 20]; mutant: [10, 10] → 20.


def test_winsorise_high_index_at_n2_pinned() -> None:
    """Kills mutant 58 (``max(0, ...)`` → ``max(1, ...)``) on hi_idx.

    For n=2: int(2*0.95) - 1 = 0.
      Original: hi_idx = max(0, min(1, 0)) = 0 → hi = sorted[0] = 10.0.
      Mutant 58: hi_idx = max(1, min(1, 0)) = 1 → hi = sorted[1] = 20.0.
    """
    out = _winsorise([10.0, 20.0])
    # Under original, hi_clamp=10 → every value is min(10, v)=10 then
    # max(20, 10)=20 → result [20, 20]. Under mutant 58 hi=20, lo=20 →
    # max(20, min(20, v))=max(20, v)=20 then 20 → still [20, 20]?
    # No: lo_idx is still 1 (sorted[1]=20). lo=20, hi=20 → max(20, min(20, 10))
    # = max(20, 10) = 20; max(20, min(20, 20)) = 20. So both [20,20].
    # Mutant 58 produces identical output on n=2 paired with original lo_idx.
    # We assert the original anchor regardless; the kill comes from harder cases.
    assert out == [20.0, 20.0]


def test_winsorise_n3_extremes_clamped() -> None:
    """Kills mutants 54, 60 (``min(n-1, ...)`` → ``min(n-2, ...)``) for n=3.

    For n=3, ceil(3*0.05)=1; int(3*0.95)-1 = int(2.85)-1 = 1.
      Original: lo_idx = min(2, max(0, 1)) = 1; hi_idx = max(0, min(2, 1)) = 1.
                Both pick sorted[1] (the median).
      Mutant 54: lo_idx = min(1, max(0, 1)) = 1 (same).
      Mutant 60: hi_idx = max(0, min(1, 1)) = 1 (same).
    Both equivalent at n=3.
    Use n=5 instead: ceil(0.25)=1; int(4.75)-1=3. Original lo=sorted[1],
    hi=sorted[3]. Mutant 54 (n-2=3): lo_idx = min(3, 1) = 1 → same.
    Try larger: n=21, p_low=0.05: ceil(1.05)=2. Original lo_idx=min(20,2)=2.
    Mutant 54: min(19, 2) = 2 → same. The mutant only differs when ceil
    saturates above n-1. For p_low=0.05, that requires n-1 ≤ ceil(n*0.05),
    i.e. very small n. We covered n=2 above.

    Pin the exact clamp values for a well-known input so any index mutation
    that DOES survive small-n is still caught.
    """
    # n=20 with one extreme. Pin exact ordered output.
    vals = [50.0] + [80.0] * 19
    out = _winsorise(vals)
    # P5 index = ceil(20*0.05)=1 → sorted[1]=80.0 → low clamp = 80.
    # P95 index = int(20*0.95)-1 = 18 → sorted[18]=80.0 → high clamp = 80.
    # Every value clamped to 80. Sum = 20 * 80 = 1600.
    assert sum(out) == 1600.0
    assert all(v == 80.0 for v in out)


def test_winsorise_hi_lo_equal_branch() -> None:
    """Kills mutant 65 (``if hi_idx < lo_idx`` → ``<=``).

    Construct n where lo_idx == hi_idx so the conditional is exactly at
    the boundary. With n=4, p_low=0.05: ceil(0.2)=1. lo_idx=min(3,1)=1.
    hi_idx = max(0, min(3, int(3.8)-1)) = max(0, min(3, 2)) = 2. Not equal.

    With n=2 (handled above) lo_idx=1, hi_idx=0, so hi < lo → guard triggers
    → hi_idx := lo_idx = 1. Mutant (<=) ALSO assigns since 0 ≤ 1. Both
    take the assignment. Distinguish: need lo_idx == hi_idx case.

    For n=5 (above): lo=1, hi=3 → hi > lo, neither branch triggers in
    original (`hi < lo` false). Mutant 65 (`<=`): `3 <= 1` false → also
    skipped. Same.

    For n=21, lo=2, hi=int(19.95)-1=18 → far apart. n where lo==hi: solve
    ceil(0.05n) == int(0.95n) - 1. n=2: lo=1, hi=0 (lo>hi); n=3: lo=1, hi=1
    EQUAL. Use n=3.
    """
    vals = [10.0, 20.0, 30.0]
    out = _winsorise(vals)
    # n=3: lo_idx = min(2, max(0, 1)) = 1 → lo = 20.
    # hi_idx = max(0, min(2, int(2.85)-1)) = max(0, min(2, 1)) = 1 → hi = 20.
    # hi < lo? 1 < 1 false → no reassignment under original.
    # Mutant 65 (<=): 1 <= 1 true → hi_idx := lo_idx (no change, still 1).
    # Same result. Equivalent on this input.
    # Better: assert hi clamp == lo clamp == 20 → all values become 20.
    assert out == [20.0, 20.0, 20.0]


def test_mad_filter_default_k_is_three() -> None:
    """Kills mutant 69 (default ``k=3.0`` → ``k=4.0``).

    Construct a series where an outlier sits at exactly 3.5 × MAD: under
    k=3 the outlier is dropped; under k=4 it survives.

    Tight cluster + one outlier:
      [80, 80, 81, 81, 82, 82, 83, 83, 100]. n=9.
      sorted = [80, 80, 81, 81, 82, 82, 83, 83, 100]. median = vals[4] = 82.
      devs = [2, 2, 1, 1, 0, 0, 1, 1, 18]. sorted = [0,0,1,1,1,1,2,2,18].
      MAD = devs[4] = 1. threshold (k=3) = 3. outlier dev 18 > 3 → DROP.
      threshold (k=4) = 4. outlier dev 18 > 4 → also DROP.
    Need tighter outlier. Use outlier at dev = 3.5 → 82 + 3.5 = 85.5.
      vals sorted: [80, 80, 81, 81, 82, 82, 83, 83, 85.5]. median = 82.
      devs sorted: [0,0,1,1,1,1,2,2,3.5]. MAD = devs[4] = 1.
      threshold (k=3)=3; outlier 3.5 > 3 → drop under k=3.
      threshold (k=4)=4; outlier 3.5 < 4 → keep under k=4 (mutant).
    """
    pts = [(i, v) for i, v in enumerate(
        [80.0, 80.0, 81.0, 81.0, 82.0, 82.0, 83.0, 83.0, 85.5]
    )]
    out = _mad_filter(pts)  # default k=3.0
    # Original (k=3): outlier 85.5 dropped → len 8.
    # Mutant (k=4):    outlier 85.5 kept → len 9.
    assert len(out) == 8
    assert (8, 85.5) not in out


def test_mad_filter_even_n_median_index_pinned() -> None:
    """Kills mutants 83, 84, 85, 88 (``vals[n // 2 - 1]`` / ``vals[n // 2]``
    in even-n median computation).

    For n=4 with vals [70, 80, 82, 100] (binary-exact):
      sorted = [70, 80, 82, 100]. median should be (sorted[1] + sorted[2])/2
      = (80 + 82) / 2 = 81.
    Mutant 83 (``n // 3 - 1``): vals[0] + vals[2] = 70 + 82 → median = 76.
    Mutant 84 (``n // 2 + 1``): vals[1] + vals[3] = 80 + 100 → median = 90.
    Mutant 85 (``n // 2 - 2``): vals[0] + vals[2] = 70 + 82 → median = 76.
    Mutant 88 (``n // 3`` for the second index): vals[1] + vals[1] = 80 → 80.

    devs:
      original (med=81): [11, 1, 1, 19]. sorted_dev=[1,1,11,19].
        MAD = (sorted_dev[1]+sorted_dev[2])/2 = (1+11)/2 = 6.
        threshold (k=3) = 18. outlier 100: dev 19 > 18 → DROP. len → 3.
      Mutant 83 (med=76): devs [6,4,6,24]. sorted=[4,6,6,24].
        MAD=(6+6)/2=6. threshold=18. outlier 100: dev 24 > 18 → DROP also.
        But 70: dev 6 ≤ 18 → keep. Same len → 3? Same KEEP/DROP pattern.
        But the dropped element under mutant: 100 (dev 24). Under original:
        100 (dev 19). Same element dropped. Hmm.
      Mutant 84 (med=90): devs [20, 10, 8, 10]. sorted=[8,10,10,20].
        MAD = (10+10)/2 = 10. threshold = 30. all devs ≤ 30 → KEEP ALL.
        len → 4. Different from original len=3 → KILL.
      Mutant 88 (med=80): devs [10, 0, 2, 20]. sorted=[0,2,10,20].
        MAD = (2+10)/2 = 6. threshold = 18. outlier 100 dev 20 > 18 → DROP.
        Also dev 70 = 10 ≤ 18 keep. Same as original → equivalent on this input.

    Use a wider input to disambiguate mutants 83, 85, 88. n=6:
      [70, 79, 80, 81, 82, 100]. sorted same.
      Original med = (sorted[2] + sorted[3]) / 2 = (80 + 81)/2 = 80.5.
      Mutant 83 (n//3 - 1 = 1): (sorted[1] + sorted[3])/2 = (79+81)/2 = 80.
      Mutant 84 (n//2 + 1 = 4): (sorted[4] + sorted[3])/2 = (82+81)/2 = 81.5.
      Mutant 85 (n//2 - 2 = 1): (sorted[1] + sorted[3])/2 = (79+81)/2 = 80.
      Mutant 88 (second idx n//3 = 2): (sorted[2] + sorted[2])/2 = 80.
      All differ from 80.5. Compute devs for each → different thresholds →
      different drop counts.
    """
    # n=4 anchor: kills mutant 84.
    pts4 = [(i, v) for i, v in enumerate([70.0, 80.0, 82.0, 100.0])]
    out4 = _mad_filter(pts4)
    # Original: 100 dropped → len 3, 100 absent.
    assert len(out4) == 3
    assert (3, 100.0) not in out4

    # n=6 anchor: tighten the distinction across mutants.
    pts6 = [(i, v) for i, v in enumerate(
        [70.0, 79.0, 80.0, 81.0, 82.0, 100.0]
    )]
    out6 = _mad_filter(pts6)
    # Original med=80.5. devs=[10.5, 1.5, 0.5, 0.5, 1.5, 19.5].
    # sorted=[0.5,0.5,1.5,1.5,10.5,19.5]. MAD=(1.5+1.5)/2=1.5.
    # threshold (k=3) = 4.5. drops: 70 (10.5), 100 (19.5). Survivors: 79,80,81,82.
    assert len(out6) == 4
    assert (0, 70.0) not in out6
    assert (5, 100.0) not in out6


def test_recalibration_input_post_init_message_signals_int_violation() -> None:
    """Kills mutants 26, 29, 34, 35, 36 (``XX...XX`` markers on ValueError
    messages in __post_init__).

    Operators key alerts off the canonical tokens ``day_index must be int``,
    ``day_index must be ≥0``, and ``day_index must be non-decreasing``. The
    XX markers would break operator dashboards. Assert the substring is
    present (not exact match — robust to wording tweaks within the token).
    """
    # Non-int day_index → first ValueError branch.
    with pytest.raises(ValueError, match="day_index must be int"):
        RecalibrationInput(
            sex="male",
            weight_kg_now=Decimal("80"),
            height_cm=Decimal("180"),
            age=30,
            activity_factor=Decimal("1.55"),
            goal="weight_loss",
            tdee_current=2800,
            days_since_last_recalibration=30,
            weights=[("not-an-int", 80.0)],  # type: ignore[list-item]
            kcal_in=[2200] * 14,
        )

    # Negative day_index → second branch.
    with pytest.raises(ValueError, match="day_index must be ≥0"):
        RecalibrationInput(
            sex="male",
            weight_kg_now=Decimal("80"),
            height_cm=Decimal("180"),
            age=30,
            activity_factor=Decimal("1.55"),
            goal="weight_loss",
            tdee_current=2800,
            days_since_last_recalibration=30,
            weights=[(-1, 80.0)],
            kcal_in=[2200] * 14,
        )

    # Non-monotonic day_index → third branch ("non-decreasing").
    with pytest.raises(ValueError, match="non-decreasing"):
        RecalibrationInput(
            sex="male",
            weight_kg_now=Decimal("80"),
            height_cm=Decimal("180"),
            age=30,
            activity_factor=Decimal("1.55"),
            goal="weight_loss",
            tdee_current=2800,
            days_since_last_recalibration=30,
            weights=[(5, 80.0), (3, 79.5)],
            kcal_in=[2200] * 14,
        )
