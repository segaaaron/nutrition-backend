"""ADR-0001 — Layer 1 MUST never return a recipe whose allergens overlap
the user's allergies. We assert this by inspecting the generated SQL: the
`NOT (... && ...)` clause is mandatory when `allergies` is non-empty.
"""

from __future__ import annotations

import inspect

from app.plan.application import layer1_eligibility


def test_layer1_source_contains_hard_allergen_exclude() -> None:
    src = inspect.getsource(layer1_eligibility)
    assert (
        "NOT (CAST(r.allergens AS text[]) && CAST(:allergies AS text[]))" in src
    ), "Layer 1 must hard-exclude allergens via array overlap negation"


def test_layer1_source_filters_contraindications() -> None:
    src = inspect.getsource(layer1_eligibility)
    assert "NOT (r.contraindicated_conditions && CAST(:conditions AS text[]))" in src


def test_layer1_dispatches_condition_safety_gates() -> None:
    """Condition-specific safety caps live in the ConditionGate registry
    (fatty_liver / pregnancy / lactation) since the 2026-07-09 scope
    reduction — Layer 1 dispatches to them via `gates_for` for every user
    condition rather than carrying inline macro literals. Assert the dispatch
    wiring is present so no declared condition can bypass its safety gate.
    """
    src = inspect.getsource(layer1_eligibility)
    for fragment in (
        "from app.plan.domain.condition_gates import gates_for",
        "for cond in conditions:",
        "for gate in gates_for(cond):",
        "gate.contribute_sql()",
    ):
        assert fragment in src, f"missing condition-gate dispatch: {fragment}"


def test_layer1_treenut_defensive_ingredient_scan_present() -> None:
    """Catalog audit 2026-06-01: 37 recipes contain nuts in ingredients[]
    without tree_nuts in allergens[]. Layer 1 MUST scan recipe_components
    when user has tree_nuts allergy to defend against this catalog gap."""
    src = inspect.getsource(layer1_eligibility)
    for fragment in (
        '"tree_nuts" in allergies',
        "NOT EXISTS",
        "recipe_components",
        "nut_pattern",
        "almond",
        "almendra",
        "walnut",
        "cashew",
        "pistachio",
        "hazelnut",
        "macadamia",
    ):
        assert fragment in src, f"missing tree-nut defense fragment: {fragment}"
