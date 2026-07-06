"""D15 — WarningCollector dedup invariant.

Pregnancy/lactation gates no longer emit micronutrient warning markers —
the micro-threshold filter was removed (empty catalog pool, 2026-07-05).
This file retains the WarningCollector unit tests that are independent
of those gates.
"""

from __future__ import annotations

from app.plan.domain.condition_gates._warnings import (
    MicronutrientDataIncompleteWarning,
    WarningCollector,
)


def test_collector_deduplicates_identical_markers() -> None:
    collector = WarningCollector()
    w = MicronutrientDataIncompleteWarning(condition="lactation", column="folate_ug")
    collector.add(w)
    collector.add(w)
    assert len(collector.items) == 1


def test_collector_accepts_distinct_columns() -> None:
    collector = WarningCollector()
    for col in ("folate_ug", "calcium_mg", "iron_mg"):
        collector.add(MicronutrientDataIncompleteWarning(condition="lactation", column=col))
    assert len(collector.items) == 3


def test_warning_serialises_to_plan_output_dict() -> None:
    w = MicronutrientDataIncompleteWarning(condition="lactation", column="folate_ug")
    d = w.to_dict()
    assert d["code"] == "micronutrient_data_incomplete"
    assert d["condition"] == "lactation"
    assert d["column"] == "folate_ug"
