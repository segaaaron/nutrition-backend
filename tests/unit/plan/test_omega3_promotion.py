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


# Mediterranean-pattern steer (legumes up, red meat down) for fatty_liver.
def test_masld_steer_uses_catalog_tags() -> None:
    assert l3._LEGUME_TAG == "legumes"
    assert l3._RED_MEAT_TAGS == frozenset({"beef", "pork"})


def test_masld_steer_weights_are_minority_signals() -> None:
    # Nudges on top of the safety gate — never dominate the composite.
    assert 0.0 < l3._LEGUME_BONUS_WEIGHT <= 0.20
    assert 0.0 < l3._RED_MEAT_PENALTY_WEIGHT <= 0.25


def test_red_meat_penalty_outweighs_legume_bonus() -> None:
    # ≤1/week red meat is a firmer target than ≥3/week legumes, so the
    # push-down must be at least as strong as the pull-up.
    assert l3._RED_MEAT_PENALTY_WEIGHT >= l3._LEGUME_BONUS_WEIGHT


# High glycemic-load penalty (refined carbs / fructose) for fatty_liver.
def test_gl_penalty_low_gl_no_penalty() -> None:
    from app.plan.application.taste_profile import gl_penalty

    assert gl_penalty(None) == 0.0  # unknown → never penalized
    assert gl_penalty(0) == 0.0
    assert gl_penalty(10) == 0.0    # low band boundary


def test_gl_penalty_ramps_and_saturates() -> None:
    from app.plan.application.taste_profile import gl_penalty

    assert 0.0 < gl_penalty(15) < 1.0   # medium → partial
    assert gl_penalty(25) == 1.0        # high → full
    assert gl_penalty(40) == 1.0        # capped


def test_gl_penalty_weight_is_minority_signal() -> None:
    assert 0.0 < l3._GL_PENALTY_WEIGHT <= 0.20
