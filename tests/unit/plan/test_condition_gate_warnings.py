"""D15 — pregnancy/lactation gates must surface a warning when their
COALESCE-based filter rejects catalog rows for missing micronutrient data.

Catalog backfill of folate/iron/calcium is still in progress (2026-06-03).
Gates currently treat NULL → 0 → recipe excluded (fail-closed, safe). But
this can silently empty the candidate pool. We require gates to emit a
machine-readable warning marker into a collector so the plan output's
`warnings[]` array surfaces "micronutrient_data_incomplete" with the
relevant condition + column.
"""

from __future__ import annotations

from app.plan.domain.condition_gates._warnings import (
    MicronutrientDataIncompleteWarning,
    WarningCollector,
)
from app.plan.domain.condition_gates.lactation import LactationGate
from app.plan.domain.condition_gates.pregnancy import PregnancyGate


def test_lactation_gate_emits_warning_markers():
    collector = WarningCollector()
    gate = LactationGate()
    gate.emit_warnings(collector)
    columns = {w.column for w in collector.items}
    assert columns == {"folate_ug", "calcium_mg", "iron_mg"}
    assert all(w.condition == "lactation" for w in collector.items)
    assert all(isinstance(w, MicronutrientDataIncompleteWarning) for w in collector.items)


def test_pregnancy_gate_emits_warning_markers():
    collector = WarningCollector()
    gate = PregnancyGate()
    gate.emit_warnings(collector)
    columns = {w.column for w in collector.items}
    assert columns == {"folate_ug", "calcium_mg", "iron_mg"}
    assert all(w.condition == "pregnancy" for w in collector.items)


def test_warning_serialises_to_plan_output_dict():
    """Plan output `warnings[]` consumes a dict shape; verify projection."""
    collector = WarningCollector()
    LactationGate().emit_warnings(collector)
    serialised = [w.to_dict() for w in collector.items]
    assert all(
        d["code"] == "micronutrient_data_incomplete"
        and d["condition"] == "lactation"
        and "column" in d
        for d in serialised
    )


def test_collector_is_idempotent_on_dedupe():
    """Calling emit_warnings twice should not duplicate identical markers."""
    collector = WarningCollector()
    gate = LactationGate()
    gate.emit_warnings(collector)
    gate.emit_warnings(collector)
    # 3 unique columns, deduped
    assert len(collector.items) == 3
