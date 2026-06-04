"""R4 — macro back-adjust graceful fallback tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.plan.domain.macro_calculator import (
    DEFAULT_MACRO_RATIOS,
    MacroBackAdjustFailed,
    back_adjust_macros,
    back_adjust_macros_with_fallback,
)


def test_fallback_returns_default_ratios_for_maintain_when_back_adjust_fails():
    # Force failure: protein + fat alone already exceed target kcal.
    p_in = Decimal("300")
    f_in = Decimal("200")
    target = Decimal("1000")
    result = back_adjust_macros_with_fallback(
        target_kcal=target, protein_g=p_in, fat_g=f_in, goal="maintain"
    )
    assert result.warning is not None
    assert "fallback" in result.warning.lower()
    # Default 30P / 30F / 40C → 1000 kcal → 75g P / 33.33g F / 100g C (1g rounding)
    expected_p = Decimal("75")
    expected_f = Decimal("33")
    expected_c = Decimal("100")
    assert result.protein_g == expected_p
    assert result.fat_g == expected_f
    assert result.carbs_g == expected_c


def test_fallback_not_applied_on_success_path():
    p_in = Decimal("120")
    f_in = Decimal("60")
    target = Decimal("2000")
    result = back_adjust_macros_with_fallback(
        target_kcal=target, protein_g=p_in, fat_g=f_in, goal="maintain"
    )
    assert result.warning is None
    # Direct back_adjust result, protein/fat preserved
    assert result.protein_g == p_in
    assert result.fat_g == f_in


def test_fallback_ratios_per_goal_anchor():
    assert DEFAULT_MACRO_RATIOS["maintain"] == (
        Decimal("0.30"),
        Decimal("0.30"),
        Decimal("0.40"),
    )
    assert DEFAULT_MACRO_RATIOS["weight_loss"] == (
        Decimal("0.35"),
        Decimal("0.30"),
        Decimal("0.35"),
    )
    assert DEFAULT_MACRO_RATIOS["muscle_gain"] == (
        Decimal("0.30"),
        Decimal("0.25"),
        Decimal("0.45"),
    )
    assert DEFAULT_MACRO_RATIOS["weight_gain"] == (
        Decimal("0.25"),
        Decimal("0.30"),
        Decimal("0.45"),
    )


def test_back_adjust_still_raises_directly_for_existing_callers():
    """Direct callers retain the original raise contract for backward compat."""
    with pytest.raises(MacroBackAdjustFailed):
        back_adjust_macros(Decimal("500"), Decimal("200"), Decimal("150"))


def test_fallback_each_goal_produces_valid_kcal_distribution():
    target = Decimal("2000")
    for goal in ("maintain", "weight_loss", "muscle_gain", "weight_gain"):
        result = back_adjust_macros_with_fallback(
            target_kcal=target,
            protein_g=Decimal("999"),
            fat_g=Decimal("999"),
            goal=goal,
        )
        # all returns fallback because protein+fat overflow target
        assert result.warning is not None
        derived = (
            result.protein_g * Decimal("4")
            + result.carbs_g * Decimal("4")
            + result.fat_g * Decimal("9")
        )
        # within 5% of target
        assert abs(derived - target) / target < Decimal("0.05")
