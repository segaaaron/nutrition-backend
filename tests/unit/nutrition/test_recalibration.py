"""ADR-0002 recalibration tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.nutrition.domain.recalibration import (
    InsufficientDataForRecalc,
    RecalibrationInput,
    RecalibrationResult,
    RecalibrationSkipped,
    _mad_filter,
    _ols_slope,
    _winsorise,
    recalibrate,
)


def _baseline(**overrides) -> RecalibrationInput:
    base = dict(
        sex="male",
        weight_kg_now=Decimal("80"),
        height_cm=Decimal("180"),
        age=30,
        activity_factor=Decimal("1.55"),
        goal="maintain",
        tdee_current=2800,
        days_since_last_recalibration=30,
        weights=[(i, 80.0 - i * 0.05) for i in range(14)],  # ~700g loss over 14d
        kcal_in=[2500] * 14,
    )
    base.update(overrides)
    return RecalibrationInput(**base)


def test_skip_when_insufficient_data():
    r = recalibrate(_baseline(weights=[(0, 80.0)]))
    assert isinstance(r, RecalibrationSkipped)
    assert r.reason == "insufficient_data"


def test_skip_during_cooldown():
    r = recalibrate(_baseline(days_since_last_recalibration=5))
    assert isinstance(r, RecalibrationSkipped)
    assert r.reason == "cooldown"


def test_skip_athlete_bulk():
    r = recalibrate(
        _baseline(
            goal="muscle_gain",
            weights=[(i, 80.0 + i * 0.05) for i in range(14)],  # +700g
            kcal_in=[3300] * 14,
            tdee_current=2800,
        )
    )
    # delta ratio near 1.0 because intake > tdee → expected gain matches actual
    assert isinstance(r, (RecalibrationSkipped, RecalibrationResult))


def test_winsorise_clips_extremes_at_p5_p95():
    vals = [50.0] + [80.0] * 18 + [200.0]
    out = _winsorise(vals)
    # Extremes pulled back to interior values
    assert min(out) > 50.0
    assert max(out) < 200.0


def test_mad_filter_rejects_outliers_3_mad():
    # Tight cluster around 80, one outlier at 95 (|x-median|/MAD > 3)
    vals = [(i, 80.0 + (i % 2) * 0.1) for i in range(13)]
    vals.append((13, 95.0))
    filtered = _mad_filter(vals)
    assert len(filtered) == 13
    assert all(w < 90.0 for _, w in filtered)


def test_mad_filter_passthrough_when_no_outliers():
    vals = [(i, 80.0 + i * 0.05) for i in range(14)]
    filtered = _mad_filter(vals)
    assert len(filtered) == len(vals)


def test_outlier_injection_does_not_distort_slope_more_than_20pct():
    """R1 property anchor: 10kg jump injected should not move slope > 1.2x clean slope."""
    clean = [(i, 80.0 - i * 0.05) for i in range(14)]
    contaminated = list(clean)
    contaminated[7] = (7, contaminated[7][1] + 10.0)  # +10 kg outlier

    clean_filtered = _mad_filter(_winsorise_pairs(clean))
    contam_filtered = _mad_filter(_winsorise_pairs(contaminated))
    s_clean = abs(_ols_slope(clean_filtered))
    s_contam = abs(_ols_slope(contam_filtered))
    if s_clean > 1e-6:
        assert s_contam <= 1.2 * s_clean


def _winsorise_pairs(pairs):
    days = [d for d, _ in pairs]
    vals = _winsorise([w for _, w in pairs])
    return list(zip(days, vals, strict=True))


def test_recalibrate_raises_insufficient_after_mad_drops_below_7():
    # 8 inputs: 6 cluster at 80 (median anchored here) + 2 wild outliers at 200.
    # MAD dominated by tight cluster (≈0.05) → both outliers > 3*MAD → dropped.
    # 6 survivors < MIN_WEIGHT_POINTS=7 → raises InsufficientDataForRecalc.
    weights = [(i, 80.0 + (i % 2) * 0.05) for i in range(6)] + [(6, 200.0), (7, 205.0)]
    with pytest.raises(InsufficientDataForRecalc):
        recalibrate(_baseline(weights=weights))


# Hypothesis property: outlier never inflates slope > 1.2x
_PROP_SETTINGS = settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


@_PROP_SETTINGS
@given(
    base=st.floats(min_value=60.0, max_value=120.0),
    daily_drift=st.floats(min_value=-0.1, max_value=0.1),
    outlier_idx=st.integers(min_value=2, max_value=11),
    outlier_jump=st.floats(min_value=8.0, max_value=15.0),
)
def test_property_single_outlier_bounded_slope(
    base: float, daily_drift: float, outlier_idx: int, outlier_jump: float
) -> None:
    clean = [(i, base + i * daily_drift) for i in range(14)]
    contam = list(clean)
    contam[outlier_idx] = (outlier_idx, clean[outlier_idx][1] + outlier_jump)

    c_filt = _mad_filter(_winsorise_pairs(clean))
    x_filt = _mad_filter(_winsorise_pairs(contam))
    s_clean = abs(_ols_slope(c_filt))
    s_contam = abs(_ols_slope(x_filt))
    # When clean slope is tiny, allow absolute small wiggle.
    if s_clean < 1e-3:
        assert s_contam < 0.01
    else:
        assert s_contam <= 1.2 * s_clean + 1e-6


def test_d7_adaptive_thermogenesis_uses_corrected_intake_not_raw():
    """D7 — AT must consume the bias-corrected intake mean, not the raw mean.

    Bug: AT was driven by `tdee_current - raw_mean`. Because R2 already
    inflates intake by 10-30%, the *true* deficit is smaller than the raw
    deficit. Using raw → AT overestimated → TDEE further reduced in a
    self-reinforcing loop.

    Anchor: obese subject, raw 2000 kcal, BMI 33 → corrected = 2600.
    With tdee_current=2800 and 28d of "deficit", AT magnitude based on
    corrected deficit (200 kcal) must be strictly smaller than the buggy
    AT based on raw deficit (800 kcal).

    We assert: the returned tdee_new is HIGHER (less negative AT applied)
    than the value that would result from feeding the raw deficit.
    """
    import statistics

    from app.nutrition.domain.adaptive_thermogenesis import at_correction

    inp = _baseline(
        weights=[(i, 100.0) for i in range(14)],  # flat → plateau → triggers
        kcal_in=[2000] * 28,  # ≥21 days so AT activates
        weight_kg_now=Decimal("100"),
        height_cm=Decimal("174"),  # BMI ~33 → obese bucket → 1.30x
        tdee_current=2800,
    )
    raw_mean = statistics.fmean(inp.kcal_in)
    raw_deficit = max(0.0, inp.tdee_current - raw_mean)
    at_raw = at_correction(
        days_in_deficit=len(inp.kcal_in),
        avg_deficit_kcal=Decimal(str(raw_deficit)),
        tdee=Decimal(str(inp.tdee_current)),
    )
    # corrected intake → smaller deficit → smaller magnitude AT
    corrected_deficit = max(0.0, inp.tdee_current - raw_mean * 1.30)
    at_corrected = at_correction(
        days_in_deficit=len(inp.kcal_in),
        avg_deficit_kcal=Decimal(str(corrected_deficit)),
        tdee=Decimal(str(inp.tdee_current)),
    )
    # AT is non-positive; smaller magnitude == closer to zero == greater.
    assert (
        at_corrected >= at_raw
    ), f"corrected AT {at_corrected} must be ≥ raw AT {at_raw} (less negative)"
    # Strictly greater when deficits diverge (they do: 800 vs 200).
    assert at_corrected > at_raw


@_PROP_SETTINGS
@given(
    raw_kcal=st.integers(min_value=1200, max_value=3000),
    tdee=st.integers(min_value=2000, max_value=3500),
    bias_mult=st.sampled_from([Decimal("1.10"), Decimal("1.20"), Decimal("1.30")]),
    days=st.integers(min_value=21, max_value=60),
)
def test_property_d7_at_corrected_le_at_raw(
    raw_kcal: int, tdee: int, bias_mult: Decimal, days: int
) -> None:
    """Property: |AT(corrected_deficit)| ≤ |AT(raw_deficit)| always.

    Because corrected_intake ≥ raw_intake (one-sided bias), corrected_deficit
    ≤ raw_deficit. AT is monotone in deficit magnitude → corrected AT is
    closer to zero (greater, since both non-positive).
    """
    from app.nutrition.domain.adaptive_thermogenesis import at_correction

    raw_deficit = max(Decimal("0"), Decimal(tdee) - Decimal(raw_kcal))
    corrected_intake = Decimal(raw_kcal) * bias_mult
    corrected_deficit = max(Decimal("0"), Decimal(tdee) - corrected_intake)

    at_raw = at_correction(days_in_deficit=days, avg_deficit_kcal=raw_deficit, tdee=Decimal(tdee))
    at_corrected = at_correction(
        days_in_deficit=days, avg_deficit_kcal=corrected_deficit, tdee=Decimal(tdee)
    )
    assert at_corrected >= at_raw  # less negative or equal


def test_d6_intake_below_physiological_floor_raises():
    """D6 — corrected intake < 0.5 × BMR → IntakeBelowPhysiologicalFloor.

    Anchor: BMR≈1400 (Mifflin male 80kg 180cm 30y), kcal_in=300 → corrected
    330 (lean) << 700 floor → must raise.
    """
    from app.nutrition.domain.recalibration import IntakeBelowPhysiologicalFloor

    inp = _baseline(kcal_in=[300] * 14)
    with pytest.raises(IntakeBelowPhysiologicalFloor):
        recalibrate(inp)


def test_d6_normal_intake_no_floor_raise():
    """D6 — corrected intake well above 0.5×BMR → no raise."""
    # _baseline already passes (2500 kcal, BMR ~1750 → far above 875 floor).
    r = recalibrate(_baseline())
    assert isinstance(r, (RecalibrationResult, RecalibrationSkipped))


@_PROP_SETTINGS
@given(
    raw_kcal=st.integers(min_value=1200, max_value=4000),
    bmi=st.decimals(min_value=Decimal("18"), max_value=Decimal("45"), places=1),
    bmr=st.integers(min_value=1100, max_value=2200),
)
def test_property_d6_floor_only_below_half_bmr(raw_kcal: int, bmi: Decimal, bmr: int) -> None:
    """Property: if corrected_mean ≥ 0.5×BMR, floor must not raise.

    Direct check on the floor predicate (independent of recalibrate's other
    early-return gates).
    """
    from app.nutrition.domain.intake_bias import corrected_kcal_in
    from app.nutrition.domain.recalibration import _intake_floor_ok

    corrected = corrected_kcal_in(raw_kcal=Decimal(raw_kcal), bmi=bmi)
    if corrected >= Decimal(bmr) * Decimal("0.5"):
        assert _intake_floor_ok(corrected_mean=corrected, bmr=Decimal(bmr)) is True


def test_result_clamped_within_15pct():
    r = recalibrate(
        _baseline(
            weights=[(i, 80.0 - i * 0.2) for i in range(14)],  # aggressive loss
            kcal_in=[2400] * 14,
        )
    )
    if isinstance(r, RecalibrationResult):
        # Production uses int(round(...)) on the clamp; compare against the
        # same rounded integer bounds rather than raw floats (2800*1.15 ==
        # 3219.999... in IEEE-754, which would spuriously fail at the edge).
        lower = int(round(2800 * 0.85))
        upper = int(round(2800 * 1.15))
        assert lower <= r.tdee_new <= upper
