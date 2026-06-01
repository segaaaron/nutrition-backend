"""Clinical-safety catalog patches — 2026-06-01.

Idempotent patches applied to data/meals/nova_meals_catalog.cleaned.json:

  Patch 1 — Tree-nut allergen backfill (FALCPA / EU 1169):
    If any execution.ingredients[] string contains a tree-nut token
    (EN+ES+PT+FR+DE), append "tree_nuts" to matchingCriteria.allergens
    when missing.

  Patch 2 — diabetes_t2 derecommendation for high-carb meals:
    If recipe is recommended for diabetes_t2 AND carbsG > 60, remove
    diabetes_t2 from recommendedForConditions (no contraindication added).

Each touched recipe gets an entry appended to _audit.patches; entries are
deduplicated by (date, patch) so re-runs are no-ops.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"

PATCH_DATE = "2026-06-01"
TREE_NUT_PATCH = "treenut_backfill"
TREE_NUT_REASON = "FALCPA EU1169 anaphylaxis safety"
DIABETES_PATCH = "diabetes_t2_decommend"
DIABETES_REASON = "carbsG > 60 glycemic spike risk"

TREE_NUT_REGEX = re.compile(
    r"\b("
    r"almond|almendra|walnut|nuez|cashew|maranon|marañon|"
    r"pistachio|pistacho|pecan|pacana|hazelnut|avellana|"
    r"macadamia|brazil nut|nuez de brasil|pine nut|pinon|piñon|"
    r"chestnut|castana|castaña|nut butter|"
    r"mantequilla de almendra|mantequilla de nuez|"
    r"almond flour|harina de almendra"
    r")\b",
    re.IGNORECASE,
)


def _ensure_audit_patches(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    audit = recipe.setdefault("_audit", {})
    patches = audit.setdefault("patches", [])
    return patches


def _record_patch(recipe: dict[str, Any], patch_name: str, reason: str) -> bool:
    """Append patch entry if not already present. Returns True if added."""
    patches = _ensure_audit_patches(recipe)
    for entry in patches:
        if entry.get("date") == PATCH_DATE and entry.get("patch") == patch_name:
            return False
    patches.append({"date": PATCH_DATE, "patch": patch_name, "reason": reason})
    return True


def _has_tree_nut(ingredients: list[str]) -> bool:
    for ing in ingredients:
        if isinstance(ing, str) and TREE_NUT_REGEX.search(ing):
            return True
    return False


def apply_tree_nut_backfill(recipe: dict[str, Any]) -> bool:
    execution = recipe.get("execution", {}) or {}
    ingredients = execution.get("ingredients", []) or []
    if not _has_tree_nut(ingredients):
        return False

    matching = recipe.setdefault("matchingCriteria", {})
    allergens = matching.setdefault("allergens", [])
    if "tree_nuts" in allergens:
        return False

    allergens.append("tree_nuts")
    _record_patch(recipe, TREE_NUT_PATCH, TREE_NUT_REASON)
    return True


def apply_diabetes_t2_decommend(recipe: dict[str, Any]) -> bool:
    matching = recipe.get("matchingCriteria", {}) or {}
    recommended = matching.get("recommendedForConditions", []) or []
    if "diabetes_t2" not in recommended:
        return False

    macros = (recipe.get("nutritionProfile", {}) or {}).get("macros", {}) or {}
    carbs = macros.get("carbsG")
    if carbs is None or carbs <= 60:
        return False

    recommended.remove("diabetes_t2")
    matching["recommendedForConditions"] = recommended
    _record_patch(recipe, DIABETES_PATCH, DIABETES_REASON)
    return True


def main() -> None:
    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        catalog = json.load(f)

    assert isinstance(catalog, list), "catalog must be a JSON array"
    original_count = len(catalog)

    tree_nut_hits: list[str] = []
    diabetes_hits: list[str] = []
    touched: set[str] = set()

    for recipe in catalog:
        rid = recipe.get("id", "<no-id>")
        if apply_tree_nut_backfill(recipe):
            tree_nut_hits.append(rid)
            touched.add(rid)
        if apply_diabetes_t2_decommend(recipe):
            diabetes_hits.append(rid)
            touched.add(rid)

    assert len(catalog) == original_count, "recipe count must not change"

    with CATALOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"recipes total:           {len(catalog)}")
    print(f"tree_nut patches:        {len(tree_nut_hits)}")
    print(f"diabetes_t2 patches:     {len(diabetes_hits)}")
    print(f"unique recipes touched:  {len(touched)}")
    print(f"sample tree_nut IDs:     {tree_nut_hits[:3]}")
    print(f"sample diabetes_t2 IDs:  {diabetes_hits[:3]}")


if __name__ == "__main__":
    main()
