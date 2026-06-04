"""v2-aware catalog remap + nutrition patches.

Operates on the snake_case schema produced by `migrate_catalog_schema_v2.py`.
Idempotent.

Applies:
  1. Legacy → canonical enum remap on target_goals + suitable_for_activity.
  2. Tree-nut allergen backfill (FALCPA / EU 1169).
  3. Diabetes_t2 high-carb derecommend (carbs_g > 60).

Audit entries recorded in `audit.patches[]`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parent.parent / "data" / "meals" / "nova_meals_catalog.cleaned.json"

GOAL_MAP: dict[str, str] = {
    "maintain_weight": "maintain",
    "build_muscle": "muscle_gain",
    "gain_weight": "weight_gain",
    "general_health": "health",
}
ACTIVITY_MAP: dict[str, str] = {
    "moderate": "moderately_active",
    "active": "very_active",
}

_TREE_NUT_RE = re.compile(
    r"\b(almond|almendra|walnut|nuez|cashew|mara[nñ][oó]n|pistachio|pistacho|"
    r"pecan|pacana|hazelnut|avellana|macadamia|brazil\s*nut|nuez\s*de\s*brasil|"
    r"pine\s*nut|pi[nñ]on|chestnut|casta[nñ]a|nut\s*butter|"
    r"mantequilla\s*de\s*almendra|mantequilla\s*de\s*nuez|almond\s*flour|"
    r"harina\s*de\s*almendra)\b",
    re.IGNORECASE,
)


def _remap_list(values: list[str], mapping: dict[str, str]) -> tuple[list[str], int]:
    n = 0
    out: list[str] = []
    for v in values:
        if v in mapping:
            out.append(mapping[v])
            n += 1
        else:
            out.append(v)
    return out, n


def _add_audit_patch(recipe: dict[str, Any], patch: dict[str, Any]) -> None:
    audit = recipe.setdefault("audit", {})
    patches = audit.setdefault("patches", [])
    # Idempotency: skip if same (date + patch) already recorded
    key = (patch.get("date"), patch.get("patch"))
    if any((p.get("date"), p.get("patch")) == key for p in patches):
        return
    patches.append(patch)


def main() -> int:
    if not CATALOG.exists():
        print(f"missing {CATALOG}", file=sys.stderr)
        return 2

    data = json.loads(CATALOG.read_text())
    goal_changes = act_changes = treenut_changes = diabt2_changes = 0

    for r in data:
        mc = r.get("matching_criteria") or {}

        new_goals, n = _remap_list(mc.get("target_goals", []), GOAL_MAP)
        if n:
            mc["target_goals"] = new_goals
            goal_changes += n

        new_act, n = _remap_list(mc.get("suitable_for_activity", []), ACTIVITY_MAP)
        if n:
            mc["suitable_for_activity"] = new_act
            act_changes += n

        # Tree-nut allergen backfill
        ingredients = (r.get("execution") or {}).get("ingredients") or []
        text = " ".join(ingredients)
        if _TREE_NUT_RE.search(text):
            allergens = mc.setdefault("allergens", [])
            if "tree_nuts" not in allergens:
                allergens.append("tree_nuts")
                treenut_changes += 1
                _add_audit_patch(r, {
                    "date": "2026-06-01",
                    "patch": "treenut_backfill",
                    "reason": "FALCPA EU1169 anaphylaxis safety",
                })

        # Diabetes_t2 high-carb derecommend
        recs = mc.get("recommended_for_conditions") or []
        carbs = ((r.get("nutrition_profile") or {}).get("macros") or {}).get("carbs_g") or 0
        if "diabetes_t2" in recs and carbs > 60:
            mc["recommended_for_conditions"] = [c for c in recs if c != "diabetes_t2"]
            diabt2_changes += 1
            _add_audit_patch(r, {
                "date": "2026-06-01",
                "patch": "diabetes_t2_decommend",
                "reason": "carbs_g > 60 glycemic spike risk",
            })

    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(
        f"v2 remap+patch | recipes={len(data)} "
        f"goals_remapped={goal_changes} activity_remapped={act_changes} "
        f"treenut_backfill={treenut_changes} diabetes_t2_decommend={diabt2_changes}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
