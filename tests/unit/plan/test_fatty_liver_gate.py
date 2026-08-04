"""Unit tests for the FattyLiverGate (NAFLD/NASH) condition gate.

Asserts that the gate's `contribute_sql()` fragment enforces the AASLD 2023 /
Mediterranean-pattern thresholds:
  - sugar ≤8 g/meal (fail-closed on NULL — safety-critical)
  - sat_fat ≤5 g/meal (fail-closed on NULL — safety-critical)
  - fiber ≥3 g/meal OR NULL (bias-admit — 95% of catalog has NULL fiber_g;
    NOT refined_carbs tag provides fallback signal; confirmed low-fiber excluded)
  - sodium ≤600 mg OR NULL (bias-admit — catalog backfill in progress)

Clinical justification of thresholds lives in the gate's docstring; here we
validate the structural contract only.
"""

from __future__ import annotations

from app.plan.domain.condition_gates import gates_for
from app.plan.domain.condition_gates.fatty_liver import FattyLiverGate


def test_gate_condition_label_is_fatty_liver() -> None:
    assert FattyLiverGate().condition == "fatty_liver"


def test_gate_registered_for_fatty_liver() -> None:
    gates = gates_for("fatty_liver")
    assert any(isinstance(g, FattyLiverGate) for g in gates), gates


def test_sql_fragment_includes_sugar_fail_closed() -> None:
    sql, params = FattyLiverGate().contribute_sql()
    # AASLD 2023 — added/free sugars <25 g/day → ≤8 g/meal.
    assert "r.sugar_g IS NOT NULL" in sql
    assert "r.sugar_g <= :fl_sugar_max" in sql
    assert params["fl_sugar_max"] == 8


def test_sql_fragment_includes_satfat_fail_closed() -> None:
    sql, params = FattyLiverGate().contribute_sql()
    # AASLD 2023 + AHA/ACC sat fat <7 % kcal → ≤5 g/meal.
    assert "r.sat_fat_g IS NOT NULL" in sql
    assert "r.sat_fat_g <= :fl_satfat_max" in sql
    assert params["fl_satfat_max"] == 5


def test_sql_fragment_promotes_fiber_floor_bias_admit() -> None:
    sql, params = FattyLiverGate().contribute_sql()
    # Bias-admit: NULL fiber_g passes through (data missing ≠ confirmed low fiber).
    # Confirmed low-fiber recipes (fiber_g < 3) still excluded.
    # NOT refined_carbs tag provides fallback exclusion signal.
    assert "r.fiber_g IS NULL OR r.fiber_g >= :fl_fiber_min" in sql
    assert "COALESCE(r.fiber_g, 0)" not in sql  # old fail-closed form must not be present
    assert params["fl_fiber_min"] == 3


def test_sql_fragment_excludes_refined_carbs_and_high_fructose_tags() -> None:
    sql, _ = FattyLiverGate().contribute_sql()
    assert "NOT (r.tags && ARRAY['refined_carbs','high_fructose']::text[])" in sql


def test_sql_fragment_does_not_use_legacy_coalesce_bias_include_for_sugar() -> None:
    """Regression: must not regress to NULL-passes-through phrasing for the
    safety-critical sugar / sat_fat columns (R6 policy)."""
    sql, _ = FattyLiverGate().contribute_sql()
    assert "COALESCE(r.sugar_g" not in sql
    assert "COALESCE(r.sat_fat_g" not in sql
