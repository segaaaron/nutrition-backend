"""Unit tests for the LactationGate condition gate.

The gate enforces:
  - `pregnancy_safe = TRUE` (no raw fish, soft cheese, high-Hg fish,
    alcohol, liver/organ — same safe-set as pregnancy).
  - `folate_ug >= 150` per portion (≥600 µg/day across 4 meals; IOM
    DRI 2002 lactation RDA 500 µg DFE/day).
  - `calcium_mg >= 300` per portion (≥1000 mg/day; IOM DRI 2011).
  - `iron_mg >= 4` per portion (≥16 mg/day for post-partum repletion;
    IOM DRI 2002 baseline 9 mg/day RDA).

NULL micronutrient values are COALESCEd to 0 → recipe excluded
(strict-positive safety bias). Catalog rows without backfill are deferred.

Sources: IOM DRI 2002 / 2011; WHO Infant and Young Child Feeding 2009;
AAP Breastfeeding 2022.
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


def test_sql_fragment_folate_floor_150() -> None:
    sql, params = LactationGate().contribute_sql()
    assert "COALESCE(r.folate_ug, 0) >= :lac_folate_min" in sql
    assert params["lac_folate_min"] == 150


def test_sql_fragment_calcium_floor_300() -> None:
    sql, params = LactationGate().contribute_sql()
    assert "COALESCE(r.calcium_mg, 0) >= :lac_calcium_min" in sql
    assert params["lac_calcium_min"] == 300


def test_sql_fragment_iron_floor_4() -> None:
    sql, params = LactationGate().contribute_sql()
    assert "COALESCE(r.iron_mg, 0) >= :lac_iron_min" in sql
    assert params["lac_iron_min"] == 4
