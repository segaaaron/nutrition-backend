"""Declare every recipe's allergens from its components, not from its title.

PERMANENT script. Re-run after any catalog change; the audit gates on it.

`recipes.allergens` was previously set by hand per batch, which let 33 recipes
reach PROD carrying an allergen they never declared — "Bread with Peanut
Butter, Banana and Egg" with `Crema de maní` in its components and no `peanuts`
flag among them. Layer 1 excludes on `r.allergens`, never on ingredients, so an
undeclared allergen is served to the allergic user. In the US that is FALCPA /
FASTER Act exposure, not a data-quality nit.

Derivation is deterministic:

    recipe_components.free_text_name
      -> ingredient_resolver.resolve_key()          (USDA reference key)
      -> data/nutrition_reference/ingredient_allergens.json

The script only ADDS allergens. An allergen already declared but not implied by
any component is left in place: a human may know something the ingredient list
does not say (shared fryer, brand-specific recipe), and silently dropping a
declaration is the one direction that can hurt someone.

Usage:
    python3 scripts/derive_allergens.py --dry-run
    python3 scripts/derive_allergens.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingredient_resolver import resolve_key  # noqa: E402

_ALLERGEN_MAP_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "nutrition_reference" / "ingredient_allergens.json"
)


def load_map() -> dict[str, list[str]]:
    raw = json.loads(_ALLERGEN_MAP_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


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

    allergen_map = load_map()

    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(dsn)
    try:
        valid = {
            r["v"] for r in await conn.fetch(
                "SELECT unnest(enum_range(NULL::allergen_enum))::text AS v")
        }
        bad = {a for v in allergen_map.values() for a in v} - valid
        if bad:
            print(f"ABORT: allergen map uses values absent from allergen_enum: {sorted(bad)}",
                  file=sys.stderr)
            return 1

        recipes = await conn.fetch(
            "SELECT id, name_en, source_batch, "
            "COALESCE(allergens, '{}')::text[] AS declared FROM recipes ORDER BY id")
        comps = await conn.fetch(
            "SELECT recipe_id, free_text_name FROM recipe_components")

        by_recipe: dict = {}
        for c in comps:
            by_recipe.setdefault(c["recipe_id"], []).append(c["free_text_name"])

        additions, added_counter = [], Counter()
        for r in recipes:
            implied: set[str] = set()
            for name in by_recipe.get(r["id"], []):
                implied.update(allergen_map.get(resolve_key(name), ()))
            missing = implied - set(r["declared"])
            if missing:
                merged = sorted(set(r["declared"]) | implied)
                additions.append((r, sorted(missing), merged))
                added_counter.update(missing)

        print(f"recipes scanned            : {len(recipes)}")
        print(f"recipes missing allergens  : {len(additions)}")
        print(f"allergen declarations added: {sum(added_counter.values())}")
        print("\nby allergen:")
        for allergen, n in added_counter.most_common():
            print(f"  {allergen:<12} +{n}")

        print("\n--- recipes gaining a HIGH-SEVERITY allergen (anaphylaxis risk) ---")
        severe = {"peanuts", "tree_nuts", "shellfish", "fish", "sesame"}
        shown = 0
        for r, missing, _ in additions:
            hits = [a for a in missing if a in severe]
            if hits:
                shown += 1
                print(f"  +{','.join(hits):<22} {r['name_en'][:52]:<54} [{r['source_batch']}]")
        if not shown:
            print("  none")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        async with conn.transaction():
            for r, _, merged in additions:
                await conn.execute(
                    "UPDATE recipes SET allergens = $1::text[]::allergen_enum[] WHERE id = $2",
                    merged, r["id"])

        print(f"\nAPPLIED — {len(additions)} recipes updated.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
