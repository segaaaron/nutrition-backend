"""Recompute every recipe's nutrition from its components against USDA.

PERMANENT script (not one-shot): re-runnable after any catalog change, and the
remediation path whenever the audit reports zeroed or drifted nutrition.

What it does, in order:

1. **Rescale broken portions.** A recipe whose computed kcal falls outside the
   generous slot band was mis-portioned at authoring time (e.g. the snacks
   stored as `kcal=130` that actually compute to 300-460 kcal). Every component
   is multiplied by one factor so the recipe lands on its official band
   midpoint. Ratios — and therefore the dish — are preserved; only the serving
   size changes. Factors are clamped to [0.25, 3.0]; anything needing more is
   reported, never silently mangled.

2. **Recompute all 13 nutrients** from `recipe_components` x USDA per-100 g
   values via `ingredient_resolver`, and write them back. `kcal` is derived by
   Atwater (4/4/9) from the recomputed macros, so stored kcal can never
   contradict stored macros.

Nothing is invented: an ingredient that does not resolve to a USDA entry aborts
the run rather than defaulting to zero.

Usage:
    python3 scripts/recompute_catalog_nutrition.py --dry-run
    python3 scripts/recompute_catalog_nutrition.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingredient_resolver import compute_recipe, unresolved  # noqa: E402

# Official slot bands (CLAUDE.md "REGLA PRINCIPAL — Creación de recetas").
# Rescaling targets the midpoint of these.
OFFICIAL_BANDS: dict[str, tuple[int, int]] = {
    "breakfast": (350, 500),
    "lunch": (550, 750),
    "dinner": (420, 600),
    "snack": (80, 160),
}

# Outer bands. Inside these a recipe is considered correctly portioned and is
# left alone — the plan engine's own +-10% scaling absorbs the difference.
# Outside them the portion is broken and gets rescaled.
OUTER_BANDS: dict[str, tuple[int, int]] = {
    "breakfast": (300, 700),
    "lunch": (450, 900),
    "dinner": (380, 850),
    "snack": (70, 200),
}

MIN_FACTOR = Decimal("0.25")
MAX_FACTOR = Decimal("3.0")

# recipes columns written back, keyed by resolver nutrient field.
COLUMN_MAP: dict[str, str] = {
    "kcal": "kcal",
    "protein_g": "protein_g",
    "carbs_g": "carbs_g",
    "fat_g": "fat_g",
    "fiber_g": "fiber_g",
    "sugar_g": "sugar_g",
    "added_sugar_g": "added_sugar_g",
    "sodium_mg": "sodium_mg",
    "sat_fat_g": "sat_fat_g",
    "potassium_mg": "potassium_mg",
    "phosphorus_mg": "phosphorus_mg",
    "calcium_mg": "calcium_mg",
    "folate_ug": "folate_ug",
}
# iron_mg is numeric(6,2); every other column above is integer.
DECIMAL_COLUMNS = {"iron_mg"}

# DIRECTIONAL ROUNDING on the columns a safety gate reads.
#
# The macro columns are INTEGER and cannot be widened without breaking the
# mobile response schemas (`int | None`). With plain half-up rounding a recipe
# carrying 5.4 g of saturated fat stores as 5 and slips under the fatty-liver
# cap of 5. So every column where MORE is worse rounds UP, and fiber — where
# more is better, and the gate is a >= 3 floor — rounds DOWN. Integer storage
# can then never make a recipe look safer than it is.
CEIL_COLUMNS = frozenset({"sat_fat_g", "sugar_g", "added_sugar_g", "sodium_mg"})
FLOOR_COLUMNS = frozenset({"fiber_g"})


def _int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _store(field: str, value: Decimal) -> int:
    if field in CEIL_COLUMNS:
        return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))
    if field in FLOOR_COLUMNS:
        return int(value.quantize(Decimal("1"), rounding=ROUND_FLOOR))
    return _int(value)


def _dec2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _stored_kcal(nutrition: dict[str, Decimal]) -> int:
    """The integer kcal that will land in the column: Atwater over the ROUNDED
    macros, so stored kcal and stored macros can never disagree."""
    return (
        _int(nutrition["protein_g"]) * 4
        + _int(nutrition["carbs_g"]) * 4
        + _int(nutrition["fat_g"]) * 9
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(dsn)
    try:
        recipes = await conn.fetch(
            "SELECT id, name_en, meal_time::text AS mt, source_batch, kcal "
            "FROM recipes ORDER BY id"
        )
        comps = await conn.fetch(
            "SELECT id, recipe_id, free_text_name, amount_g FROM recipe_components"
        )

        bad = unresolved(sorted({c["free_text_name"] for c in comps}))
        if bad:
            print(
                f"ABORT: {len(bad)} ingredient names do not resolve to USDA. "
                "Add them to ingredient_aliases.json or ingredient_extra_usda.json "
                "before recomputing — nutrition is never defaulted to zero.",
                file=sys.stderr,
            )
            for name in bad:
                print(f"  {name!r}", file=sys.stderr)
            return 1

        by_recipe: dict = {}
        for c in comps:
            by_recipe.setdefault(c["recipe_id"], []).append(c)

        rescaled, out_of_reach, no_components, updates = [], [], [], []

        for r in recipes:
            rows = by_recipe.get(r["id"])
            if not rows:
                no_components.append(r)
                continue

            items = [(c["free_text_name"], float(c["amount_g"])) for c in rows]
            nutrition = compute_recipe(items)
            slot = r["mt"]
            factor = Decimal("1")

            # Band membership is judged on the INTEGER kcal that will actually
            # be stored, not on the Decimal total. The macro columns are
            # integers, so deriving kcal from the rounded macros can move it by
            # up to 8.5 kcal — enough to leave a recipe 3 kcal outside its band
            # while the Decimal value looked fine.
            outer = OUTER_BANDS.get(slot)
            if outer and not (outer[0] <= _stored_kcal(nutrition) <= outer[1]):
                lo, hi = OFFICIAL_BANDS[slot]
                target = Decimal(lo + hi) / 2
                factor = target / nutrition["kcal"]
                if not (MIN_FACTOR <= factor <= MAX_FACTOR):
                    out_of_reach.append((r, _stored_kcal(nutrition), float(factor)))
                    factor = Decimal("1")
                else:
                    items = [(n, float(Decimal(str(g)) * factor)) for n, g in items]
                    new_nutrition = compute_recipe(items)
                    rescaled.append(
                        (r, _stored_kcal(nutrition), _stored_kcal(new_nutrition), float(factor))
                    )
                    nutrition = new_nutrition

            updates.append((r, rows, factor, nutrition))

        print(f"recipes           : {len(recipes)}")
        print(f"  recomputed      : {len(updates)}")
        print(f"  rescaled        : {len(rescaled)}")
        print(f"  factor out of range (left alone): {len(out_of_reach)}")
        print(f"  NO components (skipped)        : {len(no_components)}")

        if rescaled:
            print("\n--- rescaled portions ---")
            for r, before, after, f in sorted(rescaled, key=lambda x: x[3])[:60]:
                print(
                    f"  x{f:>5.2f}  {before:>6d} -> {after:>5d} kcal  "
                    f"[{r['mt']:<9}] {r['name_en'][:46]}"
                )
        if out_of_reach:
            print("\n--- NEEDS MANUAL REVIEW (factor outside [0.25, 3.0]) ---")
            for r, kcal, f in out_of_reach:
                print(f"  computed={kcal:>7d} kcal, factor {f:.2f}  {r['name_en'][:56]}")
        if no_components:
            print("\n--- NO components, nutrition not traceable ---")
            for r in no_components:
                print(f"  [{r['source_batch']}] {r['name_en'][:60]}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        set_clause = ", ".join(
            f"{col} = ${i + 2}" for i, col in enumerate([*COLUMN_MAP.values(), "iron_mg"])
        )
        sql = f"UPDATE recipes SET {set_clause} WHERE id = $1"  # noqa: S608

        n_scaled_rows = 0
        async with conn.transaction():
            for r, rows, factor, nutrition in updates:
                if factor != 1:
                    for c in rows:
                        await conn.execute(
                            "UPDATE recipe_components SET amount_g = $1 WHERE id = $2",
                            float(Decimal(str(c["amount_g"])) * factor),
                            c["id"],
                        )
                        n_scaled_rows += 1
                rounded = {field: _store(field, nutrition[field]) for field in COLUMN_MAP}
                # The macro columns are INTEGER. Rounding protein/carbs/fat
                # independently can shift Atwater by up to 8.5 kcal, which on a
                # 120 kcal snack breaks MACRO_TOLERANCE (0.02). Deriving kcal
                # from the ALREADY-ROUNDED macros makes stored kcal exactly
                # consistent with stored macros by construction.
                rounded["kcal"] = (
                    rounded["protein_g"] * 4 + rounded["carbs_g"] * 4 + rounded["fat_g"] * 9
                )
                values = [rounded[field] for field in COLUMN_MAP]
                values.append(_dec2(nutrition["iron_mg"]))
                await conn.execute(sql, r["id"], *values)

        print(f"\nAPPLIED — {len(updates)} recipes updated, {n_scaled_rows} component rows rescaled.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
