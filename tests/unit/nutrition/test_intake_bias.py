"""R2 — self-report intake bias correction tests.

Source citations validated against:
- Lichtman SW et al. 1992 (NEJM 327:1893) — obese subjects under-report energy
  intake by ~47% (≈1.3x correction).
- Hill RJ, Davies PSW 1985/2001 (Br J Nutr) — lean subjects under-report ~10-15%.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.nutrition.domain.intake_bias import (
    BIAS_MULTIPLIERS,
    corrected_kcal_in,
)


def test_lean_bucket_applies_10pct_correction():
    out = corrected_kcal_in(raw_kcal=Decimal("2000"), bmi=Decimal("22"))
    assert out == Decimal("2200.00")


def test_overweight_bucket_applies_20pct_correction():
    out = corrected_kcal_in(raw_kcal=Decimal("2000"), bmi=Decimal("27.5"))
    assert out == Decimal("2400.00")


def test_obese_bucket_applies_30pct_correction():
    out = corrected_kcal_in(raw_kcal=Decimal("2000"), bmi=Decimal("33"))
    assert out == Decimal("2600.00")


def test_boundary_25_uses_overweight_bucket():
    # BMI exactly 25 → overweight bucket (>=25)
    out = corrected_kcal_in(raw_kcal=Decimal("2000"), bmi=Decimal("25"))
    assert out == Decimal("2400.00")


def test_boundary_30_uses_obese_bucket():
    out = corrected_kcal_in(raw_kcal=Decimal("2000"), bmi=Decimal("30"))
    assert out == Decimal("2600.00")


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    raw=st.decimals(min_value=Decimal("800"), max_value=Decimal("5000"), places=0),
    bmi=st.decimals(min_value=Decimal("15"), max_value=Decimal("50"), places=1),
)
def test_property_corrected_always_ge_raw(raw: Decimal, bmi: Decimal) -> None:
    """Correction is always inflationary (under-reporting bias is one-sided)."""
    out = corrected_kcal_in(raw_kcal=raw, bmi=bmi)
    assert out >= raw


def test_multipliers_match_published_anchors():
    assert BIAS_MULTIPLIERS["lean"] == Decimal("1.10")
    assert BIAS_MULTIPLIERS["overweight"] == Decimal("1.20")
    assert BIAS_MULTIPLIERS["obese"] == Decimal("1.30")
