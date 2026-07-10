"""Sprint A1 — per-meal rationale ("why this recipe"). Fact-based, no over-claim."""

from __future__ import annotations

from app.plan.domain.meal_rationale import build_meal_rationale


def test_high_protein_and_goal_combined() -> None:
    r = build_meal_rationale(protein_g=33, fiber_g=2, meal_time="breakfast", goal="weight_loss")
    assert r["es"] == "Alto en proteína (33 g) y apoya tu meta de bajar de peso."
    assert r["en"] == "High in protein (33 g) and supports your weight-loss goal."


def test_protein_fiber_and_goal_three_clauses() -> None:
    r = build_meal_rationale(protein_g=40, fiber_g=8, meal_time="lunch", goal="muscle_gain")
    assert "Alto en proteína (40 g)" in r["es"]
    assert "buena fibra (8 g)" in r["es"]
    assert "apoya tu ganancia muscular" in r["es"]
    assert r["es"].endswith(".")


def test_low_protein_snack_only_goal_clause() -> None:
    # 10g < snack threshold 12 → no protein clause; fiber < 5 → none; only goal.
    r = build_meal_rationale(protein_g=10, fiber_g=2, meal_time="snack", goal="weight_gain")
    assert "proteína" not in r["es"]
    assert r["es"] == "Aporta energía para subir de peso."


def test_no_goal_and_no_highlights_falls_back_neutral() -> None:
    r = build_meal_rationale(protein_g=8, fiber_g=1, meal_time="snack", goal=None)
    assert r["es"] == "Comida equilibrada para tu plan."
    assert r["en"] == "A balanced meal for your plan."


def test_no_overclaim_when_numbers_missing() -> None:
    # None macros must never produce a protein/fiber clause.
    r = build_meal_rationale(protein_g=None, fiber_g=None, meal_time="dinner", goal="health")
    assert "proteína" not in r["es"] and "fibra" not in r["es"]
    assert "equilibrada" in r["es"]
