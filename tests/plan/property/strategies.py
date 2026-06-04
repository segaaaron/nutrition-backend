"""Shared hypothesis strategies for plan H1 property tests.

All strategies produce Decimal values within the realistic adult nutrition
population range. No floats. No randomness outside hypothesis.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from hypothesis import strategies as st

Sex = Literal["male", "female"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
Activity = Literal[
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]


def decimal_in_range(lo: str, hi: str, places: int = 1) -> st.SearchStrategy[Decimal]:
    """Bounded Decimal strategy with fixed places. No NaN, no Infinity."""
    return st.decimals(
        min_value=Decimal(lo),
        max_value=Decimal(hi),
        allow_nan=False,
        allow_infinity=False,
        places=places,
    )


weight_kg: st.SearchStrategy[Decimal] = decimal_in_range("40", "200", places=1)
height_cm: st.SearchStrategy[Decimal] = decimal_in_range("140", "210", places=1)
age: st.SearchStrategy[int] = st.integers(min_value=18, max_value=80)
sex: st.SearchStrategy[Sex] = st.sampled_from(["male", "female"])
goal: st.SearchStrategy[Goal] = st.sampled_from(
    ["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
)
activity: st.SearchStrategy[Activity] = st.sampled_from(
    ["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
)
bodyfat_pct: st.SearchStrategy[Decimal | None] = st.one_of(
    st.none(), decimal_in_range("3", "60", places=1)
)
kcal_target: st.SearchStrategy[Decimal] = decimal_in_range("1200", "4000", places=0)

# Macro inputs for back-adjust. Protein/fat are pre-quantised to 1g.
protein_g: st.SearchStrategy[Decimal] = decimal_in_range("30", "300", places=0)
fat_g: st.SearchStrategy[Decimal] = decimal_in_range("20", "200", places=0)
carbs_g: st.SearchStrategy[Decimal] = decimal_in_range("50", "600", places=0)

# BMR values for safety floor tests.
bmr_decimal: st.SearchStrategy[Decimal] = decimal_in_range("800", "3000", places=0)
