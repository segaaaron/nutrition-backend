"""Merge liquid + bulk batches into the master catalog.

- Reads data/meals/nova_meals_catalog.cleaned.json (master).
- Appends data/meals/liquid_batch_2026_06_01.json and bulk_batch_2026_06_01.json.
- Idempotent: dedupes by `id` (existing master ids win).
- Validates each new recipe (enum closure + macro consistency ≤5%) before append.
- Rejected entries written to scripts/merge_catalog_batches_rejections.log.

Run: uv run python scripts/merge_catalog_batches.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import (  # noqa: E402
    ACTIVITY_LEVELS_5, ALLERGENS_14, CONDITIONS_25, GOALS_5, MEAL_TIMES_4, REGIONS_5,
)

MASTER = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
LIQUID = ROOT / "data" / "meals" / "liquid_batch_2026_06_01.json"
BULK = ROOT / "data" / "meals" / "bulk_batch_2026_06_01.json"
L99 = ROOT / "data" / "meals" / "l99_batch_2026_06_01.json"
GAP = ROOT / "data" / "meals" / "gap_closure_batch_2026_06_01.json"
ROUND2 = ROOT / "data" / "meals" / "round2_batch_2026_06_01.json"
COND_HELPFUL = ROOT / "data" / "meals" / "condition_helpful_batch_2026_06_01.json"
VIRAL = ROOT / "data" / "meals" / "viral_juices_2026_06_01.json"
ROUND3 = ROOT / "data" / "meals" / "round3_batch_2026_06_01.json"
LOG = ROOT / "scripts" / "merge_catalog_batches_rejections.log"


def validate(recipe: dict) -> tuple[bool, str]:
    mc = recipe.get("matching_criteria") or {}
    np = recipe.get("nutrition_profile") or {}
    m = np.get("macros") or {}
    kcal = np.get("calories", 0)
    if not isinstance(kcal, (int, float)) or kcal <= 0:
        return False, "kcal_invalid"
    p, c, f = m.get("protein_g", 0), m.get("carbs_g", 0), m.get("fat_g", 0)
    if abs((4 * p + 4 * c + 9 * f) - kcal) / kcal > 0.05:
        return False, "macro_drift>5%"
    for v in mc.get("allergens", []):
        if v not in ALLERGENS_14: return False, f"allergen_drift={v}"
    for v in mc.get("recommended_for_conditions", []):
        if v not in CONDITIONS_25: return False, f"rec_drift={v}"
    for v in mc.get("contraindicated_conditions", []):
        if v not in CONDITIONS_25: return False, f"contra_drift={v}"
    for v in mc.get("target_goals", []):
        if v not in GOALS_5: return False, f"goal_drift={v}"
    for v in mc.get("suitable_for_activity", []):
        if v not in ACTIVITY_LEVELS_5: return False, f"activity_drift={v}"
    for v in mc.get("regions", []):
        if v not in REGIONS_5: return False, f"region_drift={v}"
    mt = (recipe.get("execution") or {}).get("meal_time")
    if mt not in MEAL_TIMES_4: return False, f"meal_time_drift={mt}"
    if not recipe.get("id"):
        return False, "missing_id"
    return True, "ok"


def main() -> None:
    master = json.loads(MASTER.read_text())
    assert isinstance(master, list)
    existing_ids = {r["id"] for r in master if isinstance(r, dict) and "id" in r}
    added: list[dict] = []
    rejected: list[tuple[str, str]] = []

    for batch_path in (LIQUID, BULK, L99, GAP, ROUND2, COND_HELPFUL, VIRAL, ROUND3):
        if not batch_path.exists():
            continue
        batch = json.loads(batch_path.read_text())
        assert isinstance(batch, list)
        for r in batch:
            if not isinstance(r, dict):
                rejected.append(("?", "not_a_dict"))
                continue
            rid = r.get("id", "?")
            if rid in existing_ids:
                rejected.append((rid, "dedupe_existing_id"))
                continue
            ok, reason = validate(r)
            if not ok:
                rejected.append((rid, reason))
                continue
            existing_ids.add(rid)
            added.append(r)
            master.append(r)

    MASTER.write_text(json.dumps(master, ensure_ascii=False))
    LOG.write_text(
        f"existing_before={len(master)-len(added)}\nadded={len(added)}\n"
        f"total_after={len(master)}\nrejected={len(rejected)}\n\n"
        + "\n".join(f"{rid}\t{reason}" for rid, reason in rejected[:200])
    )
    print(f"merge: added={len(added)} rejected={len(rejected)} total_after={len(master)}")


if __name__ == "__main__":
    main()
