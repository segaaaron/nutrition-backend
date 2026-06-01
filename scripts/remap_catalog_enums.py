"""Remap legacy enum values in nova_meals_catalog.cleaned.json.

Legacy → canonical (matches Postgres enum schema, ADR-0001):
  goals:    maintain_weight→maintain, build_muscle→muscle_gain,
            gain_weight→weight_gain, general_health→health
  activity: moderate→moderately_active, active→very_active

Idempotent: re-running on already-remapped catalog is a no-op.
Writes a sibling backup `.bak` on first run only.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

GOAL_MAP = {
    "maintain_weight": "maintain",
    "build_muscle": "muscle_gain",
    "gain_weight": "weight_gain",
    "general_health": "health",
}
ACTIVITY_MAP = {
    "moderate": "moderately_active",
    "active": "very_active",
}

CATALOG = Path(__file__).resolve().parent.parent / "data" / "meals" / "nova_meals_catalog.cleaned.json"


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


def main() -> int:
    if not CATALOG.exists():
        print(f"missing {CATALOG}", file=sys.stderr)
        return 2

    backup = CATALOG.with_suffix(CATALOG.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(CATALOG, backup)
        print(f"backup written: {backup}")

    data = json.loads(CATALOG.read_text())
    goal_changes = act_changes = 0
    for r in data:
        mc = r.get("matchingCriteria") or {}
        if "targetGoals" in mc:
            mc["targetGoals"], n = _remap_list(mc["targetGoals"], GOAL_MAP)
            goal_changes += n
        if "suitableForActivity" in mc:
            mc["suitableForActivity"], n = _remap_list(mc["suitableForActivity"], ACTIVITY_MAP)
            act_changes += n

    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"remapped: goals={goal_changes} activity={act_changes} recipes={len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
