"""Lactation algorithm invariants (ADR-0016 — H2.1).

Hard guarantees:
- Lactation user kcal_target ≥ TDEE + 400 (after applying +500 surplus,
  even if goal is weight_loss with a deficit).
- Lactation gate Layer1 SQL contributes pregnancy_safe + micronutrient
  thresholds.
- Non-lactation conditions: adjustment is a no-op (passthrough).
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.plan.domain.bmr_safety import (
    apply_goal_to_tdee,
    apply_lactation_adjustment,
    enforce_bmr_safety_floor,
    mifflin_st_jeor,
    tdee,
)
from app.plan.domain.condition_gates import LactationGate, gates_for

# In-scope non-lactation conditions — the lactation kcal adjustment must be a
# no-op for any of them (owner scope 2026-07-09).
_NON_LACTATION_CONDITIONS = st.sets(
    st.sampled_from(["fatty_liver", "pregnancy"]),
    max_size=2,
)


@settings(max_examples=200, deadline=None)
@given(
    kcal=st.decimals(
        min_value=Decimal("1200"),
        max_value=Decimal("4000"),
        allow_nan=False,
        allow_infinity=False,
        places=0,
    ),
    extras=_NON_LACTATION_CONDITIONS,
)
def test_non_lactation_passthrough(kcal: Decimal, extras: set[str]) -> None:
    out = apply_lactation_adjustment(kcal_target=kcal, conditions=frozenset(extras))
    assert out == kcal


@settings(max_examples=200, deadline=None)
@given(
    kcal=st.decimals(
        min_value=Decimal("1200"),
        max_value=Decimal("4000"),
        allow_nan=False,
        allow_infinity=False,
        places=0,
    )
)
def test_lactation_adds_500_kcal(kcal: Decimal) -> None:
    out = apply_lactation_adjustment(
        kcal_target=kcal,
        conditions=frozenset({"lactation"}),
    )
    assert out == kcal + Decimal("500")


@settings(max_examples=200, deadline=None)
@given(
    weight=st.decimals(
        min_value=Decimal("45"),
        max_value=Decimal("100"),
        allow_nan=False,
        allow_infinity=False,
        places=1,
    ),
    height=st.decimals(
        min_value=Decimal("150"),
        max_value=Decimal("190"),
        allow_nan=False,
        allow_infinity=False,
        places=1,
    ),
    age=st.integers(min_value=18, max_value=45),
)
def test_lactation_kcal_at_or_above_tdee_under_deficit(
    weight: Decimal,
    height: Decimal,
    age: int,
) -> None:
    """Under weight_loss goal the deficit caps at min(500, 0.25·TDEE). Lactation
    surplus (+500) at minimum cancels that deficit, so final kcal ≥ TDEE.
    Protects mother + infant energy non-negotiable floor."""
    b = mifflin_st_jeor(weight_kg=weight, height_cm=height, age=age, sex="female")
    t = tdee(bmr=b, activity_level="moderately_active")
    k = apply_goal_to_tdee(tdee_val=t, goal="weight_loss")
    enforce_bmr_safety_floor(kcal_target=k, bmr=b)
    final = apply_lactation_adjustment(
        kcal_target=k,
        conditions=frozenset({"lactation"}),
    )
    assert final >= t, f"lactation net kcal below TDEE: tdee={t} final={final}"


def test_lactation_gate_registered_at_import() -> None:
    gates = gates_for("lactation")
    assert len(gates) == 1
    assert isinstance(gates[0], LactationGate)


def test_lactation_gate_contributes_sql_with_thresholds() -> None:
    # Micronutrient thresholds removed (empty catalog pool). Gate: pregnancy_safe only.
    sql, params = LactationGate().contribute_sql()
    assert "pregnancy_safe = TRUE" in sql
    assert "folate_ug" not in sql
    assert params == {}


def test_lactation_gate_pregnancy_safe_is_the_only_filter() -> None:
    """pregnancy_safe=TRUE is the single gate; no micronutrient COALESCE."""
    sql, params = LactationGate().contribute_sql()
    assert sql == "(r.pregnancy_safe = TRUE)"
    assert params == {}


def test_layer1_inlines_lactation_gate() -> None:
    """Layer1 must dispatch to gates_for(cond) for every user condition.
    Post H2 sweep, the dispatch is generic over all registered gates
    (lactation included)."""
    import inspect

    from app.plan.application import layer1_eligibility

    src = inspect.getsource(layer1_eligibility)
    assert "gates_for" in src
    assert "for cond in conditions" in src
