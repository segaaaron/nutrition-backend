"""Unit tests for folate_fit and sugar_penalty scoring helpers.

Mirrors the pattern of test_omega3_promotion.py: boundary conditions,
saturation, weight-range, and condition-scoping checks. These lock the
constants against drift — a mutation on _FOLATE_FULL_UG or _SUGAR_PENALTY_LOW
would cause at least one test to fail.
"""
from __future__ import annotations

from app.plan.application import layer3_ranking as l3
from app.plan.application.taste_profile import folate_fit, sugar_penalty


# ── folate_fit ────────────────────────────────────────────────────────────────

def test_folate_fit_null_zero_gives_no_boost() -> None:
    # Missing/zero data must never boost AND never penalise.
    assert folate_fit(None) == 0.0
    assert folate_fit(0) == 0.0
    assert folate_fit(-10) == 0.0


def test_folate_fit_scales_and_saturates() -> None:
    # 100 µg = half the 200 µg full-signal mark (NIH ODS DRI 600 µg/day ÷ 4 slots ≈ 150 µg/meal).
    assert folate_fit(100) == 0.5
    assert folate_fit(200) == 1.0          # saturates at full-signal mark
    assert folate_fit(400) == 1.0          # clamped — never exceeds 1.0


def test_pregnancy_and_lactation_are_folate_promoted_conditions() -> None:
    assert "pregnancy" in l3._FOLATE_PROMOTE_CONDITIONS
    assert "lactation" in l3._FOLATE_PROMOTE_CONDITIONS


def test_other_conditions_are_not_folate_promoted() -> None:
    for cond in ("fatty_liver", "diabetes_t2", "hypertension", "weight_loss"):
        assert cond not in l3._FOLATE_PROMOTE_CONDITIONS


def test_folate_bonus_weight_is_minority_signal() -> None:
    # Must nudge, not dominate (taste cosine = 0.40 is the primary signal).
    assert 0.0 < l3._FOLATE_BONUS_WEIGHT <= 0.20


# ── sugar_penalty ─────────────────────────────────────────────────────────────

def test_sugar_penalty_below_threshold_no_penalty() -> None:
    # NULL/0/at-threshold must return 0 — never penalise for missing data or
    # recipes within the WHO <25 g/day free-sugars guideline.
    assert sugar_penalty(None) == 0.0
    assert sugar_penalty(0) == 0.0
    assert sugar_penalty(25) == 0.0       # boundary: exactly at LOW → 0


def test_sugar_penalty_ramps_and_saturates() -> None:
    # Mid-range: (35 - 25) / (45 - 25) = 0.5
    assert sugar_penalty(35) == 0.5
    assert sugar_penalty(45) == 1.0       # saturates at HIGH mark
    assert sugar_penalty(100) == 1.0      # clamped — never below 1.0


def test_sugar_penalty_weight_is_mild_signal() -> None:
    # The penalty accounts for natural fruit sugar (total, not added), so
    # the weight must be low enough that a 150g mango portion (~22g sugar)
    # incurs zero penalty and a 40g-sugar smoothie is only gently demoted.
    assert 0.0 < l3._SUGAR_PENALTY_WEIGHT <= 0.15


def test_sugar_penalty_boundaries_match_who_guidance() -> None:
    from app.plan.application.taste_profile import _SUGAR_PENALTY_LOW, _SUGAR_PENALTY_HIGH

    # Low boundary aligns with WHO <25 g/day free-sugars target.
    assert _SUGAR_PENALTY_LOW == 25
    # High boundary gives a full-penalty ceiling that leaves room for the
    # ramp (HIGH - LOW must be ≥ 10 to avoid a cliff).
    assert _SUGAR_PENALTY_HIGH > _SUGAR_PENALTY_LOW + 10
