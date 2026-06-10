"""Clinical end-to-end checks for lactation kcal + hydration adjustments.

These tests exercise `apply_lactation_adjustment` (kcal) and
`calculate_water_target` (hydration) directly, mirroring the IOM DRI 2002
recommendations:

  - Exclusive lactation (0-6 months): +500 kcal/day.
  - Partial lactation (>6 months, complementary solids): +330 kcal/day.
  - Hydration: +700 ml/day baseline on top of climate / activity.

Sources: IOM DRI 2002 (Energy & Water chapters); WHO Infant and Young
Child Feeding 2009; AAP Breastfeeding 2022.
"""

from __future__ import annotations

from decimal import Decimal

from app.plan.domain.bmr_safety import apply_lactation_adjustment
from app.plan.domain.water_calculator import calculate_water_target


def test_exclusive_lactation_kcal_surplus_500() -> None:
    out = apply_lactation_adjustment(
        kcal_target=Decimal("2000"),
        conditions=frozenset({"lactation"}),
        is_exclusive=True,
    )
    assert out - Decimal("2000") == Decimal("500")


def test_partial_lactation_kcal_surplus_330() -> None:
    out = apply_lactation_adjustment(
        kcal_target=Decimal("2000"),
        conditions=frozenset({"lactation"}),
        is_exclusive=False,
    )
    assert out - Decimal("2000") == Decimal("330")


def test_unknown_breastfeeding_flag_defaults_exclusive_500() -> None:
    """When the flag is omitted (chip onboarding) we adopt the safer
    exclusive surplus to avoid under-feeding."""
    out = apply_lactation_adjustment(
        kcal_target=Decimal("2000"),
        conditions=frozenset({"lactation"}),
        is_exclusive=None,
    )
    assert out - Decimal("2000") == Decimal("500")


def test_no_lactation_no_surplus_regardless_of_flag() -> None:
    out = apply_lactation_adjustment(
        kcal_target=Decimal("2000"),
        conditions=frozenset({"diabetes_t2"}),
        is_exclusive=True,
    )
    assert out == Decimal("2000")


def test_lactation_water_target_adds_700ml() -> None:
    """Hydration must include the +700 ml lactation bump (IOM DRI 2002)."""
    base = calculate_water_target(
        weight_kg=Decimal("65"),
        kcal_daily=2000,
        activity="lightly_active",
        region="",
        month=6,
        goal="maintain",
        conditions=frozenset(),
        pregnant=False,
        lactating=False,
    )
    lac = calculate_water_target(
        weight_kg=Decimal("65"),
        kcal_daily=2000,
        activity="lightly_active",
        region="",
        month=6,
        goal="maintain",
        conditions=frozenset({"lactation"}),
        pregnant=False,
        lactating=True,
    )
    assert lac.total_ml - base.total_ml == 700
