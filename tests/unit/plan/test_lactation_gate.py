"""Unit tests for the LactationGate condition gate.

Gate enforces `pregnancy_safe = TRUE`. Micronutrient thresholds (folate/
calcium/iron) removed — produced empty candidate pool against current catalog.
"""

from __future__ import annotations

from app.plan.domain.condition_gates import gates_for
from app.plan.domain.condition_gates.lactation import LactationGate


def test_gate_condition_label_is_lactation() -> None:
    assert LactationGate().condition == "lactation"


def test_gate_registered_for_lactation() -> None:
    gates = gates_for("lactation")
    assert any(isinstance(g, LactationGate) for g in gates), gates


def test_sql_fragment_requires_pregnancy_safe() -> None:
    sql, _ = LactationGate().contribute_sql()
    assert "r.pregnancy_safe = TRUE" in sql


def test_sql_fragment_no_micronutrient_thresholds() -> None:
    sql, params = LactationGate().contribute_sql()
    assert "folate" not in sql
    assert "calcium" not in sql
    assert "iron" not in sql
    assert params == {}
