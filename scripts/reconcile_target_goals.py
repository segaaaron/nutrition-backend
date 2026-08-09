"""Strip goals a recipe's macros cannot support.

PERMANENT script. Re-runnable; the audit gates on the resulting pool depth.

`target_goals` is a promise: Layer 1 selects on it, so tagging a 2 g-protein
fruit snack `muscle_gain` means the engine will build a muscle-gain plan around
it. The 2026-08-04 audit found 274 recipes doing exactly that — "Walnuts with
apple" at 2 g of protein offered for muscle gain, a 1 g fruit plate offered for
weight loss, where protein is what preserves lean mass during a deficit.

The thresholds are CLAUDE.md's own, from the `nova-clinical-nutrition-generator`
table "Proteína mínima por slot y objetivo", which derives from ISSN 2017
(1.6-2.2 g/kg/day for body-composition goals). `health` and `weight_gain` carry
no protein floor: the first is a general-eating goal and the second is driven by
energy density, so neither makes a protein promise.

This script only REMOVES goals. It never adds one — a recipe that clears the
bar for `muscle_gain` is not thereby intended for it, and that judgement stays
with whoever authored it.

A recipe left with no goal at all keeps `health`, so it stays reachable rather
than becoming dead catalog weight.

Usage:
    python3 scripts/reconcile_target_goals.py --dry-run
    python3 scripts/reconcile_target_goals.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

# CLAUDE.md, nova-clinical-nutrition-generator §2. Protein grams per serving.
MIN_PROTEIN: dict[str, dict[str, int]] = {
    "muscle_gain": {"breakfast": 40, "lunch": 55, "dinner": 45, "snack": 15},
    "weight_loss": {"breakfast": 30, "lunch": 45, "dinner": 35, "snack": 10},
    "maintain": {"breakfast": 20, "lunch": 30, "dinner": 25, "snack": 5},
}
# Goals with no protein promise: `health` is general eating, `weight_gain` is
# driven by energy density.
UNGATED_GOALS = ("health", "weight_gain")
FALLBACK_GOAL = "health"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(dsn)
    try:
        recipes = await conn.fetch("""
            SELECT id, name_en, meal_time::text AS mt, protein_g,
                   COALESCE(target_goals, '{}')::text[] AS goals
              FROM recipes ORDER BY id
        """)

        dropped, updates, rescued = Counter(), [], 0
        for r in recipes:
            goals = set(r["goals"])
            kept = set()
            for goal in goals:
                floor = MIN_PROTEIN.get(goal, {}).get(r["mt"])
                if floor is None or (r["protein_g"] or 0) >= floor:
                    kept.add(goal)
                else:
                    dropped[f"{goal}/{r['mt']}"] += 1
            if not kept and goals:
                kept.add(FALLBACK_GOAL)
                rescued += 1
            if kept != goals:
                updates.append((r, sorted(kept)))

        print(f"recipes          : {len(recipes)}")
        print(f"recipes changing : {len(updates)}")
        print(f"  left with no goal, kept as '{FALLBACK_GOAL}': {rescued}")

        print("\n--- goals dropped (protein below the CLAUDE.md floor) ---")
        for key, n in dropped.most_common():
            goal, slot = key.split("/")
            print(f"  {goal:<12} {slot:<10} {n:>5}   (floor {MIN_PROTEIN[goal][slot]} g)")

        print("\n--- resulting pool per goal x slot ---")
        by_goal: dict[str, dict[str, int]] = {}
        changed = {u[0]["id"]: set(u[1]) for u in updates}
        for r in recipes:
            for goal in changed.get(r["id"], set(r["goals"])):
                by_goal.setdefault(goal, Counter())[r["mt"]] += 1
        slots = ["breakfast", "lunch", "dinner", "snack"]
        print(f"  {'goal':<13}" + "".join(f"{s:>13}" for s in slots))
        for goal in sorted(by_goal):
            line = f"  {goal:<13}"
            for slot in slots:
                n = by_goal[goal].get(slot, 0)
                mark = "OK" if n >= 63 else ("LOW" if n >= 21 else "!!")
                line += f"{mark:>4}{n:>9}"
            print(line)

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        async with conn.transaction():
            for r, goals in updates:
                await conn.execute(
                    "UPDATE recipes SET target_goals = $1::text[]::goal_enum[] "
                    "WHERE id = $2", goals, r["id"])

        print(f"\nAPPLIED — {len(updates)} recipes updated.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
