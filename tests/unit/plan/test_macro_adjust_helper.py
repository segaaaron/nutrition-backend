"""D2 — `safe_back_adjust` defaults to fallback + surfaces warning."""

from __future__ import annotations

from decimal import Decimal

from app.plan.application.macro_adjust import safe_back_adjust


def test_happy_path_no_warning() -> None:
    warnings: list[str] = []
    result = safe_back_adjust(
        target_kcal=Decimal("2000"),
        protein_g=Decimal("150"),
        fat_g=Decimal("70"),
        goal="maintain",
        warnings=warnings,
    )
    assert result.warning is None
    assert warnings == []
    assert result.protein_g > 0
    assert result.carbs_g > 0
    assert result.fat_g > 0


def test_infeasible_input_falls_back_and_appends_warning() -> None:
    """Protein 200 g + fat 150 g = 800+1350 = 2150 kcal cannot fit 500 kcal target.

    Direct `back_adjust_macros` raises here; the helper must absorb and
    surface a warning instead of propagating the exception.
    """
    warnings: list[str] = []
    result = safe_back_adjust(
        target_kcal=Decimal("500"),
        protein_g=Decimal("200"),
        fat_g=Decimal("150"),
        goal="weight_loss",
        warnings=warnings,
    )
    assert result.warning is not None
    assert "macro_back_adjust_fallback_applied" in result.warning
    assert warnings == [result.warning]
    # Fallback macros are positive (goal default ratios applied).
    assert result.protein_g > 0
    assert result.carbs_g > 0
    assert result.fat_g > 0


def test_warnings_list_mutated_in_place_across_calls() -> None:
    warnings: list[str] = ["existing_plan_warning"]
    safe_back_adjust(
        target_kcal=Decimal("500"),
        protein_g=Decimal("200"),
        fat_g=Decimal("150"),
        goal="weight_loss",
        warnings=warnings,
    )
    # The pre-existing warning is preserved; the fallback warning is appended.
    assert warnings[0] == "existing_plan_warning"
    assert len(warnings) == 2
    assert "macro_back_adjust_fallback_applied" in warnings[1]
