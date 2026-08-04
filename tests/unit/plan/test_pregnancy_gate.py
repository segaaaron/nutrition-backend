"""Unit tests for the PregnancyGate condition gate.

Gate enforces:
  - `pregnancy_safe = TRUE` (catalog flag: no raw fish, no unpasteurized
    cheese, no organ meat, no alcohol preparations)
  - NOT tagged `high_mercury_fish` (FDA/EPA + ACOG — methylmercury damages
    fetal CNS; prohibited species: shark, swordfish, king mackerel, marlin,
    orange roughy, bigeye tuna, tilefish)

Micronutrient thresholds (folate/iron/calcium) deferred — produced empty
candidate pool against current general-nutrition catalog.
"""

from __future__ import annotations

from app.plan.domain.condition_gates import gates_for
from app.plan.domain.condition_gates.pregnancy import PregnancyGate


def test_gate_condition_label_is_pregnancy() -> None:
    assert PregnancyGate().condition == "pregnancy"


def test_gate_registered_for_pregnancy() -> None:
    gates = gates_for("pregnancy")
    assert any(isinstance(g, PregnancyGate) for g in gates), gates


def test_sql_fragment_requires_pregnancy_safe() -> None:
    sql, _ = PregnancyGate().contribute_sql()
    assert "r.pregnancy_safe = TRUE" in sql


def test_sql_excludes_high_mercury_fish_tag() -> None:
    # FDA/EPA 2017 + ACOG: shark, swordfish, king mackerel, marlin, orange
    # roughy, bigeye tuna, tilefish prohibited during pregnancy.
    # Tag `high_mercury_fish` on any such recipe → excluded here.
    sql, _ = PregnancyGate().contribute_sql()
    assert "high_mercury_fish" in sql
    assert "NOT" in sql


def test_sql_no_params_returned() -> None:
    # Gate uses catalog flags only — no bound parameters needed.
    _, params = PregnancyGate().contribute_sql()
    assert params == {}


def test_sql_no_micronutrient_thresholds() -> None:
    sql, _ = PregnancyGate().contribute_sql()
    assert "folate" not in sql
    assert "calcium" not in sql
    assert "iron" not in sql
