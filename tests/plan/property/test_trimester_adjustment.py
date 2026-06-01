"""Trimester pregnancy energy adjustment invariants (H2.6 / bmr_safety).

IOM DRI 2002:
- Trimester 1: no kcal increase
- Trimester 2: +340 kcal/day
- Trimester 3: +452 kcal/day
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.plan.domain.bmr_safety import apply_trimester_adjustment

_KCAL_ANY: st.SearchStrategy[Decimal] = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("10000"),
    allow_nan=False, allow_infinity=False, places=0,
)
_KCAL_REALISTIC: st.SearchStrategy[Decimal] = st.decimals(
    min_value=Decimal("1200"), max_value=Decimal("4000"),
    allow_nan=False, allow_infinity=False, places=0,
)


@settings(max_examples=200, deadline=None)
@given(kcal=_KCAL_ANY)
def test_trimester_none_passthrough(kcal: Decimal) -> None:
    assert apply_trimester_adjustment(kcal_target=kcal, trimester=None) == kcal


@settings(max_examples=200, deadline=None)
@given(kcal=_KCAL_ANY)
def test_trimester_first_no_change(kcal: Decimal) -> None:
    assert apply_trimester_adjustment(kcal_target=kcal, trimester="first") == kcal


@settings(max_examples=200, deadline=None)
@given(kcal=_KCAL_ANY)
def test_trimester_second_adds_340(kcal: Decimal) -> None:
    out = apply_trimester_adjustment(kcal_target=kcal, trimester="second")
    assert out == kcal + Decimal("340")


@settings(max_examples=200, deadline=None)
@given(kcal=_KCAL_ANY)
def test_trimester_third_adds_452(kcal: Decimal) -> None:
    out = apply_trimester_adjustment(kcal_target=kcal, trimester="third")
    assert out == kcal + Decimal("452")


@settings(max_examples=200, deadline=None)
@given(kcal=_KCAL_ANY)
def test_trimester_monotonic_progression(kcal: Decimal) -> None:
    """For the same kcal input: first ≤ second ≤ third (energy needs grow)."""
    first = apply_trimester_adjustment(kcal_target=kcal, trimester="first")
    second = apply_trimester_adjustment(kcal_target=kcal, trimester="second")
    third = apply_trimester_adjustment(kcal_target=kcal, trimester="third")
    assert first <= second <= third


@settings(max_examples=200, deadline=None)
@given(
    kcal=_KCAL_ANY,
    trimester=st.sampled_from(["first", "second", "third", None]),
)
def test_trimester_deterministic(
    kcal: Decimal,
    trimester: Literal["first", "second", "third"] | None,
) -> None:
    a = apply_trimester_adjustment(kcal_target=kcal, trimester=trimester)
    b = apply_trimester_adjustment(kcal_target=kcal, trimester=trimester)
    assert a == b


@settings(max_examples=200, deadline=None)
@given(
    kcal=_KCAL_ANY,
    trimester=st.sampled_from(["first", "second", "third", None]),
)
def test_trimester_maintains_decimal_type(
    kcal: Decimal,
    trimester: Literal["first", "second", "third"] | None,
) -> None:
    out = apply_trimester_adjustment(kcal_target=kcal, trimester=trimester)
    assert isinstance(out, Decimal)


@settings(max_examples=200, deadline=None)
@given(
    kcal=_KCAL_REALISTIC,
    trimester=st.sampled_from(["first", "second", "third", None]),
)
def test_trimester_in_bounds_for_realistic_inputs(
    kcal: Decimal,
    trimester: Literal["first", "second", "third"] | None,
) -> None:
    """For clinically plausible kcal targets (1200..4000), trimester-adjusted
    output stays within (1200..5000) — caps the maximum surplus impact."""
    out = apply_trimester_adjustment(kcal_target=kcal, trimester=trimester)
    assert Decimal("1200") <= out <= Decimal("5000")
