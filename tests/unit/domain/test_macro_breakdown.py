"""Property-based starter test for MacroBreakdown.validate_tolerance.

Uses the same MACRO_TOLERANCE constant the catalog ingest gate uses.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.shared.domain.macro_tolerance import MACRO_TOLERANCE
from app.shared.domain.value_objects import MacroBreakdown


@given(
    p=st.integers(min_value=0, max_value=300),
    c=st.integers(min_value=0, max_value=600),
    f=st.integers(min_value=0, max_value=200),
)
def test_derived_kcal_matches_thermodynamic_formula(p: int, c: int, f: int) -> None:
    m = MacroBreakdown(protein_g=p, carbs_g=c, fat_g=f)
    assert m.derived_kcal() == p * 4 + c * 4 + f * 9


def test_validate_tolerance_within_2pct_passes() -> None:
    # 320 derived kcal; declare 325 (1.56% off) -> within tolerance
    m = MacroBreakdown(protein_g=20, carbs_g=40, fat_g=9)  # = 80+160+81 = 321
    assert m.validate_tolerance(325)
    assert m.validate_tolerance(321)


def test_validate_tolerance_outside_2pct_fails() -> None:
    m = MacroBreakdown(protein_g=20, carbs_g=40, fat_g=9)  # 321 kcal derived
    # 360 is 12% off → fails the 2% tolerance gate
    assert not m.validate_tolerance(360)


def test_tolerance_constant_is_locked_to_two_percent() -> None:
    # Guards against accidental relaxation of the single source of truth.
    # MACRO_TOLERANCE is Decimal('0.02') per ADR-0009 (Decimal-strict migration).
    from decimal import Decimal

    assert MACRO_TOLERANCE == Decimal("0.02")
