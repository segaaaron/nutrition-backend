"""Normalise `recipes.regions` to the three supported markets: latam / us / ca.

PERMANENT script. Re-runnable; the audit gates on its invariants.

State it repairs (2026-08-04 audit):

  * `ca` appeared on ZERO recipes although `region_mapper.country_to_region`
    maps Canada to it, so every Canadian user fell through Layer 1's region
    fallback onto the 239 legacy `world` rows.
  * Nine ISO country codes (`MX`, `CO`, `PE`, `AR`, `CL`, `BO`, `PY`, `VE`,
    `EC` — 53 recipes each) plus a lowercase `bo` (39) were left behind by
    `retag_catalog_by_country.py`, which was written for the abandoned
    per-country model of ADR-0008 and never finished. They match no market, so
    those recipes were invisible to every user.
  * 282 recipes from the five most recent batches carried `latam` only, so
    none of them reached the US market.

Tagging rule
------------
`latam` on everything — the catalog is LATAM-authored and every dish is
available there.

`us` + `ca` additionally, UNLESS the recipe is LATAM-exclusive: it uses an
ingredient that general US/Canadian retail does not carry (Andean tubers,
Amazon/Altiplano river fish), or it IS a regional prepared dish. Ingredients
that read as LATAM but are ordinary in US/Canadian supermarkets — yuca,
nopales, corn tortillas, plantain, quinoa, sweet potato, passion fruit,
panela — are NOT exclusive and do not hold a recipe back.

US and Canada share the same tag set: the two markets have equivalent food
availability, and splitting them would leave Canada at zero recipes again.

Usage:
    python3 scripts/retag_regions.py --dry-run
    python3 scripts/retag_regions.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingredient_resolver import resolve_key  # noqa: E402

SUPPORTED_MARKETS = ("latam", "us", "ca")

# USDA reference keys that general US/Canadian retail does not carry.
LATAM_EXCLUSIVE_INGREDIENTS: frozenset[str] = frozenset({
    # Andean tubers, grains and fruit
    "Chuño (papa deshidratada)", "Chuño refritos (chuño phuti)",
    "Oca (cruda)", "Olluco melloco (crudo)", "Arracacha (cruda)",
    "Papa amarilla (cruda)", "Cañihua (cocida)", "Kiwicha amaranto (cocido)",
    "Lúcuma (cruda)", "Aguaymanto uchuva (cruda)", "Curuba (cruda)",
    "Guaba pacay (pulpa)", "Jocote ciruela tropical (crudo)",
    "Níspero medlar (crudo)", "Maíz morado (seco)", "Maíz morado seco",
    "Canchita maíz tostado", "Chifles (plátano chips)",
    # River / Altiplano fish — no US or Canadian retail supply
    "Surubí bagre (cocido)", "Paiche arapaima (cocido)", "Sábalo (frito)",
    "Pacú (cocido)", "Boga (cocida, río)", "Tararira (cocida, río)",
    "Ispi carachi (cocido, Titicaca)", "Pejerrey (cocido)",
    # Regional preserved meats and cheeses
    "Charque de res (desalado)", "Mondongo (cocido)",
    "Queso de mano venezolano",
    # Regional prepared dishes
    "Ají de gallina (preparado)", "Lomo saltado (preparado)",
    "Causa limeña (porción)", "Papa a la huancaína", "Seco de pollo (guiso)",
    "Anticuchos de corazón (vaca)", "Humitas de choclo",
    "Sopa paraguaya (porción)", "Chipá (tradicional)",
    "Mazamorra morada", "Suspiro a la limeña", "Picarones (fritos)",
    "Alfajor de maicena", "Api morado (bebida boliviana)",
    "Chicha morada (bebida)", "Locoto rocoto (fresco)", "Rocoto (fresco)",
})

# Dish names that mark a recipe as regional even when every ingredient is
# individually ordinary (e.g. a llajwa built from tomato and chili).
LATAM_EXCLUSIVE_NAME_RE = re.compile(
    r"llajwa|quirqui|chu[nñ]o|locoto|rocoto|mbeju|mbej[uú]|chip[aá]|"
    r"sopa paraguaya|humita|anticucho|causa lime|aj[ií] de gallina|"
    r"lomo saltado|seco de pollo|huancain|suspiro|picarone|mazamorra|"
    r"alfajor|api morado|chicha morada|canchita|chifles|charque|mondongo|"
    r"surub[ií]|paiche|s[aá]balo|pac[uú]|tararira|ispi|carachi|pejerrey|"
    r"olluco|arracacha|ca[nñ]ihua|kiwicha|l[uú]cuma|aguaymanto|tacacho|"
    r"wallake|q'?oa",
    re.IGNORECASE,
)


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
            SELECT id, name_en, name_translations->>'es' AS name_es, source_batch,
                   meal_time::text AS mt,
                   ARRAY(SELECT btrim(x) FROM unnest(regions) x ORDER BY 1) AS rg
              FROM recipes ORDER BY id
        """)
        comps = await conn.fetch("SELECT recipe_id, free_text_name FROM recipe_components")
        by_recipe: dict = {}
        for c in comps:
            by_recipe.setdefault(c["recipe_id"], []).append(c["free_text_name"])

        changes, exclusive = [], []
        for r in recipes:
            reason = None
            for name in by_recipe.get(r["id"], []):
                key = resolve_key(name)
                if key in LATAM_EXCLUSIVE_INGREDIENTS:
                    reason = f"ingredient: {key}"
                    break
            if reason is None:
                blob = f"{r['name_en']} {r['name_es'] or ''}"
                m = LATAM_EXCLUSIVE_NAME_RE.search(blob)
                if m:
                    reason = f"name: {m.group(0)}"

            # Sorted, because the SELECT returns the stored tags sorted. Comparing
            # an unsorted literal against it would report every row as changed on
            # every run — the script must be a no-op once the catalog is correct.
            new = sorted(["latam"] if reason else ["latam", "us", "ca"])
            if reason:
                exclusive.append((r, reason))
            if list(r["rg"]) != new:
                changes.append((r, list(r["rg"]), new))

        print(f"recipes                 : {len(recipes)}")
        print(f"  LATAM-exclusive       : {len(exclusive)}")
        print(f"  universal (latam+us+ca): {len(recipes) - len(exclusive)}")
        print(f"  rows changing         : {len(changes)}")

        print("\n--- LATAM-exclusive (stay latam-only) ---")
        for r, reason in exclusive[:40]:
            print(f"  {r['name_en'][:50]:<52} {reason}")
        if len(exclusive) > 40:
            print(f"  ... and {len(exclusive) - 40} more")

        print("\n--- junk tags being removed ---")
        junk: dict[str, int] = {}
        for _r, old, _ in changes:
            for t in old:
                if t not in SUPPORTED_MARKETS:
                    junk[t] = junk.get(t, 0) + 1
        for t, n in sorted(junk.items(), key=lambda x: -x[1]):
            print(f"  {t!r:<10} removed from {n} recipes")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        async with conn.transaction():
            for r, _, new in changes:
                await conn.execute(
                    "UPDATE recipes SET regions = $1::text[]::char(5)[] WHERE id = $2",
                    new, r["id"])

        print(f"\nAPPLIED — {len(changes)} recipes retagged.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
