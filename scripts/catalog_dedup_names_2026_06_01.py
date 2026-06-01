"""Rename name-collisions with disambiguator suffix.

Functional signature dedup already enforced (0 functional duplicates). However,
template generation produced ~1,702 recipes sharing a name with another recipe
in a different (meal_time × dietary × cuisine) cell — different ingredients,
different macros, same display name. Bad UX: user sees "Snack X" 6 times with
different kcal.

Strategy: keep the first occurrence canonical; subsequent occurrences get an
explicit suffix derived from cuisine + kcal bucket. Idempotent.

Examples:
  "Snack LatAm Vegano de Frijoles Negros" (377 kcal) → unchanged
  "Snack LatAm Vegano de Frijoles Negros" (280 kcal) → "Snack LatAm Vegano de Frijoles Negros (Ligero 280 kcal)"
  "Snack LatAm Vegano de Frijoles Negros" (420 kcal) → "Snack LatAm Vegano de Frijoles Negros (Reforzado 420 kcal)"
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "data" / "meals" / "nova_meals_catalog.cleaned.json"


def _kcal_bucket(kcal: int) -> str:
    if kcal < 250:
        return "Ligero"
    if kcal < 400:
        return "Estándar"
    if kcal < 600:
        return "Reforzado"
    return "Abundante"


def main() -> int:
    data = json.loads(CATALOG.read_text())
    by_name: dict[str, list[int]] = defaultdict(list)
    for idx, r in enumerate(data):
        by_name[r["name"]].append(idx)

    renamed = 0
    for name, idxs in by_name.items():
        if len(idxs) <= 1:
            continue
        # Sort by kcal asc to keep canonical = lowest kcal version
        idxs.sort(key=lambda i: data[i]["nutrition_profile"]["calories"])
        for i in idxs[1:]:
            r = data[i]
            kcal = r["nutrition_profile"]["calories"]
            bucket = _kcal_bucket(kcal)
            new_name = f"{name} ({bucket} {kcal} kcal)"
            if r["name"] != new_name:
                r["name"] = new_name
                renamed += 1
                r.setdefault("audit", {}).setdefault("patches", []).append({
                    "date": "2026-06-01",
                    "patch": "dedup_name_disambiguator",
                    "original_name": name,
                })

    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    # Verify
    names_after = {r["name"] for r in data}
    print(f"renamed: {renamed}")
    print(f"total: {len(data)}  unique_names: {len(names_after)}  "
          f"name_uniqueness: {len(names_after)/len(data)*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
