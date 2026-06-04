"""Closed-enum drift guard for the meals catalog.

Master plan risk F13: silently expanding a vocabulary (new allergen string,
new activity tier, regional condition shorthand) breaks Layer 1 SQL filters
that cast to closed Postgres enum types. This test runs on every PR — any
value in the JSON catalog outside the closed vocabularies fails the build.

Vocabularies sourced from `app.shared.domain.vocabularies` (single runtime
source of truth, mirrors migration 0001 DDL).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.shared.domain.vocabularies import (
    ACTIVITY_LEVELS_5,
    ALLERGENS_14,
    CONDITIONS_25,
    GOALS_5,
)

CATALOG = Path(__file__).resolve().parents[2] / "data" / "meals" / "nova_meals_catalog.cleaned.json"


@pytest.fixture(scope="module")
def catalog() -> list[dict[str, object]]:
    assert CATALOG.exists(), f"catalog not found at {CATALOG}"
    data = json.loads(CATALOG.read_text())
    assert isinstance(data, list), "catalog must be a JSON array"
    return data


def _collect(catalog: list[dict[str, object]], path: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for recipe in catalog:
        node: object = recipe
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
            if node is None:
                break
        if isinstance(node, list):
            for item in node:
                if isinstance(item, str):
                    found.add(item)
    return found


def test_catalog_size_invariant(catalog: list[dict[str, object]]) -> None:
    # Relaxed 2026-06-01: catalog grows via additive batches (liquid + bulk).
    # Floor preserves seed catalog footprint; ceiling left open for further
    # bounded growth. Drift below 2000 indicates accidental deletion.
    assert len(catalog) >= 2000, f"catalog shrunk below seed floor: {len(catalog)}"


def test_allergens_within_closed_vocabulary(catalog: list[dict[str, object]]) -> None:
    observed = _collect(catalog, ("matching_criteria", "allergens"))
    drift = observed - ALLERGENS_14
    assert not drift, f"allergen drift: {sorted(drift)}"


def test_recommended_conditions_within_closed_vocabulary(catalog: list[dict[str, object]]) -> None:
    observed = _collect(catalog, ("matching_criteria", "recommended_for_conditions"))
    drift = observed - CONDITIONS_25
    assert not drift, f"recommendedForConditions drift: {sorted(drift)}"


def test_contraindicated_conditions_within_closed_vocabulary(
    catalog: list[dict[str, object]]
) -> None:
    observed = _collect(catalog, ("matching_criteria", "contraindicated_conditions"))
    drift = observed - CONDITIONS_25
    assert not drift, f"contraindicatedConditions drift: {sorted(drift)}"


def test_target_goals_within_closed_vocabulary(catalog: list[dict[str, object]]) -> None:
    observed = _collect(catalog, ("matching_criteria", "target_goals"))
    drift = observed - GOALS_5
    assert not drift, f"targetGoals drift: {sorted(drift)}"


def test_activity_levels_within_closed_vocabulary(catalog: list[dict[str, object]]) -> None:
    observed = _collect(catalog, ("matching_criteria", "suitable_for_activity"))
    drift = observed - ACTIVITY_LEVELS_5
    assert not drift, f"suitableForActivity drift: {sorted(drift)}"


def test_macro_consistency_within_5_percent(catalog: list[dict[str, object]]) -> None:
    """Master plan invariant: |kcal - (4P + 4C + 9F)| / kcal <= 0.05 (catalog ingest tolerance).

    Stricter MACRO_TOLERANCE (2%) applies to plan output post back-adjust.
    Catalog ingest tolerance loosened to 5% to absorb USDA rounding noise.
    """
    violations: list[tuple[str, float]] = []
    for recipe in catalog:
        np = recipe.get("nutrition_profile") if isinstance(recipe, dict) else None
        if not isinstance(np, dict):
            continue
        kcal = np.get("calories")
        macros = np.get("macros")
        if not isinstance(kcal, (int, float)) or not isinstance(macros, dict):
            continue
        p = macros.get("protein_g") or 0
        c = macros.get("carbs_g") or 0
        f = macros.get("fat_g") or 0
        if (
            not isinstance(p, (int, float))
            or not isinstance(c, (int, float))
            or not isinstance(f, (int, float))
        ):
            continue
        derived = 4 * p + 4 * c + 9 * f
        if kcal <= 0:
            continue
        delta = abs(derived - kcal) / kcal
        if delta > 0.05:
            rid = recipe.get("id") if isinstance(recipe, dict) else "?"
            violations.append((str(rid), delta))
    assert not violations, (
        f"{len(violations)} recipes violate macro consistency >5%: " f"sample={violations[:5]}"
    )
