"""Omega-3 promotion for fatty_liver (oily fish is first-line NAFLD diet).

Covers the pure scoring helper and the condition-scoping config wired into
Layer 3. The end-to-end ranking bonus is exercised by the plan-generation
integration suite; here we lock the deterministic pieces.
"""
from __future__ import annotations

from app.plan.application import layer3_ranking as l3
from app.plan.application.taste_profile import omega3_fit


def test_omega3_fit_unknown_or_zero_gives_no_boost() -> None:
    # NULL / 0 must never boost AND never penalize (returns exactly 0.0).
    assert omega3_fit(None) == 0.0
    assert omega3_fit(0) == 0.0
    assert omega3_fit(-5) == 0.0


def test_omega3_fit_scales_and_saturates() -> None:
    assert omega3_fit(75) == 0.5          # half of the 150 mg full-signal mark
    assert omega3_fit(150) == 1.0         # oily-fish portion → full bonus
    assert omega3_fit(500) == 1.0         # capped, never exceeds 1.0


def test_fatty_liver_is_an_omega3_promoted_condition() -> None:
    assert "fatty_liver" in l3._OMEGA3_PROMOTE_CONDITIONS


def test_out_of_scope_conditions_are_not_promoted() -> None:
    # Only in-scope conditions drive the bonus; removed medical conditions
    # must not silently re-enter through the promotion path.
    for cond in ("diabetes_t2", "hypertension", "ckd", "dyslipidemia"):
        assert cond not in l3._OMEGA3_PROMOTE_CONDITIONS


def test_omega3_bonus_weight_is_a_minority_signal() -> None:
    # The bonus nudges, it must not dominate the composite (taste=0.40).
    assert 0.0 < l3._OMEGA3_BONUS_WEIGHT <= 0.20
