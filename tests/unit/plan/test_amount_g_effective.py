"""Unit — C19: amount_g_effective in PlanMealIngredient schema."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError as PydValidationError

from app.plan.presentation.schemas import PlanMealIngredient


def test_amount_g_effective_populated():
    ing = PlanMealIngredient(
        name="Pollo",
        amount_g=Decimal("150"),
        amount_g_effective=Decimal("75.0"),
        position=1,
    )
    assert ing.amount_g_effective == Decimal("75.0")


def test_amount_g_effective_defaults_none():
    ing = PlanMealIngredient(name="Arroz", amount_g=Decimal("100"), position=1)
    assert ing.amount_g_effective is None


def test_amount_g_effective_none_when_no_adjustment():
    """No adjustment (factor == 1.0) → amount_g_effective is None."""
    ing = PlanMealIngredient(
        name="Brócoli", amount_g=Decimal("80"), amount_g_effective=None, position=2
    )
    assert ing.amount_g_effective is None


def test_effective_half_factor():
    """0.5× factor → effective is half of base amount."""
    base = Decimal("150")
    effective = Decimal(str(round(float(base) * 0.5, 1)))
    ing = PlanMealIngredient(
        name="Pollo", amount_g=base, amount_g_effective=effective, position=1
    )
    assert ing.amount_g_effective == Decimal("75.0")


def test_extra_fields_rejected():
    with pytest.raises(PydValidationError):
        PlanMealIngredient(
            name="X", amount_g=Decimal("100"), position=1, unknown="y"  # type: ignore[call-arg]
        )
