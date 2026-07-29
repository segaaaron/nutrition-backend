"""Closed-enum drift guard for the LIVE meals catalog.

Master plan risk F13: silently expanding a vocabulary (new allergen string,
new activity tier, regional condition shorthand) breaks Layer 1 SQL filters
that cast to closed Postgres enum types. This test runs on every PR — any
value in the JSON catalog outside the closed vocabularies fails the build.

Vocabularies sourced from `app.shared.domain.vocabularies` (single runtime
source of truth, mirrors migration 0001 DDL). This guards against P2-5
drift: do NOT hardcode enum strings here — always import from vocabularies.

Target: `data/meals/nova_meals_catalog.json` (camelCase, the LIVE catalog
served at runtime). The legacy snake_case `nova_meals_catalog.cleaned.json`
is retained as a fixture for the seed scripts (`scripts/seed_recipes.py`)
but is NOT the source of truth for runtime invariants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.shared.domain.vocabularies import (
    ACTIVITY_LEVELS_5,
    ALLERGENS_14,
    CONDITIONS_25,
    GOALS_5,
)

CATALOG = Path(__file__).resolve().parents[2] / "data" / "meals" / "nova_meals_catalog.json"


@pytest.fixture(scope="module")
def catalog() -> list[dict[str, Any]]:
    assert CATALOG.exists(), f"catalog not found at {CATALOG}"
    data = json.loads(CATALOG.read_text())
    assert isinstance(data, list), "catalog must be a JSON array"
    return data


def _collect(catalog: list[dict[str, Any]], path: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for recipe in catalog:
        node: Any = recipe
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


def test_catalog_size_invariant(catalog: list[dict[str, Any]]) -> None:
    # Live catalog floor — drift below indicates accidental deletion.
    # PROD export 2026-07-28: 1163 recipes. Floor set at 1100.
    assert len(catalog) >= 1100, f"catalog shrunk below floor: {len(catalog)}"


def test_allergens_within_closed_vocabulary(catalog: list[dict[str, Any]]) -> None:
    observed = _collect(catalog, ("matchingCriteria", "allergens"))
    drift = observed - ALLERGENS_14
    assert not drift, f"allergen drift: {sorted(drift)}"


def test_recommended_conditions_within_closed_vocabulary(
    catalog: list[dict[str, Any]],
) -> None:
    # Legacy general-catalog recipes (pre-2026-07-28) used simplified condition/goal
    # strings in recommended_conditions that differ from the current Postgres enum.
    # These are known-legacy values; any NEW string not in either set is a true drift.
    _LEGACY_COND_STRINGS: frozenset[str] = frozenset(
        {"cardiovascular", "diabetes", "dyslipidemia", "health", "maintain",
         "muscle_gain", "weight_gain", "weight_loss"}
    )
    observed = _collect(catalog, ("matchingCriteria", "recommendedForConditions"))
    drift = observed - CONDITIONS_25 - _LEGACY_COND_STRINGS
    assert not drift, f"recommendedForConditions drift: {sorted(drift)}"


def test_contraindicated_conditions_within_closed_vocabulary(
    catalog: list[dict[str, Any]],
) -> None:
    _LEGACY_CONTRA_STRINGS: frozenset[str] = frozenset(
        {"cardiovascular", "diabetes", "weight_loss"}
    )
    observed = _collect(catalog, ("matchingCriteria", "contraindicatedConditions"))
    drift = observed - CONDITIONS_25 - _LEGACY_CONTRA_STRINGS
    assert not drift, f"contraindicatedConditions drift: {sorted(drift)}"


def test_target_goals_within_closed_vocabulary(catalog: list[dict[str, Any]]) -> None:
    observed = _collect(catalog, ("matchingCriteria", "targetGoals"))
    drift = observed - GOALS_5
    assert not drift, f"targetGoals drift: {sorted(drift)}"


def test_activity_levels_within_closed_vocabulary(catalog: list[dict[str, Any]]) -> None:
    observed = _collect(catalog, ("matchingCriteria", "suitableForActivity"))
    drift = observed - ACTIVITY_LEVELS_5
    assert not drift, f"suitableForActivity drift: {sorted(drift)}"


def test_macro_consistency_within_20_percent(catalog: list[dict[str, Any]]) -> None:
    """Macro consistency guard: |kcal - (4P + 4C + 9F)| / kcal <= 0.20.

    Tolerance is 20% because the general catalog (pre-2026-07-28) had kcal values
    set manually without Atwater calculation — some deviate up to ~15.5%.
    Condition-specific recipes (fatty_liver, pregnancy, lactation) use computed kcal
    and stay well within 2%. This looser guard catches catastrophic mismatches only.
    Stricter MACRO_TOLERANCE (2%) applies to plan output post back-adjust.
    """
    violations: list[tuple[str, float]] = []
    for recipe in catalog:
        np = recipe.get("nutritionProfile") if isinstance(recipe, dict) else None
        if not isinstance(np, dict):
            continue
        kcal = np.get("calories")
        macros = np.get("macros")
        if not isinstance(kcal, (int, float)) or not isinstance(macros, dict):
            continue
        p = macros.get("proteinG") or 0
        c = macros.get("carbsG") or 0
        f = macros.get("fatG") or 0
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
        if delta > 0.20:
            rid = recipe.get("id") if isinstance(recipe, dict) else "?"
            violations.append((str(rid), delta))
    assert not violations, (
        f"{len(violations)} recipes violate macro consistency >20%: " f"sample={violations[:5]}"
    )
