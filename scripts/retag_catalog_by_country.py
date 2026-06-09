"""Re-tag recipe catalog by country-specific cultural markers.

PHASE 1 of the cultural-fit fix (owner directive 2026-06-07):
the existing catalogue tags ~95% of recipes with the coarse bucket
``latam``, which lets Mexican-coded recipes (tacos, burritos, etc.)
dominate plans for non-Mexican LATAM users. This script re-classifies
each recipe by matching country-specific markers in ``name_en`` and
overwrites ``recipes.regions`` so the Layer 1 eligibility filter +
``cultural_fit()`` can route by user country.

Behaviour
---------
- Recipes whose name matches a country pattern (taco → MX, ceviche → PE,
  salteña → BO, etc.) → ``regions = ['<COUNTRY>']``.
- Everything else → ``regions = ['neutral']``.
- US/EU/UK/CA tags are dropped (they were noise — most of the catalogue
  is universal healthy food, not country-specific).

Usage
-----
    python -m scripts.retag_catalog_by_country --dry-run    # report only
    python -m scripts.retag_catalog_by_country              # apply changes

Idempotent: re-running produces the same outcome.

The script reads ``DATABASE_URL`` from the environment. Run against the
target DB you intend to mutate (prod via SSH, local via docker compose).
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter

from sqlalchemy import text

from app.core.db import dispose_engine, session_scope

# Country marker patterns. Matches against ``recipes.name_en``.
# Word boundaries + case insensitive. Designed conservative: only obvious
# culture markers, never generic words like "pollo" or "arroz".
PATTERNS: dict[str, str] = {
    "MX": (
        r"\b(taco|tacos|burrito|burritos|enchilada|quesadilla|fajita|fajitas|"
        r"chimichanga|mole poblano|chilaquile|huevo[s]? ranchero|"
        r"tortilla de ma[ií]z|tortilla mexicana|tinga|cochinita pibil|"
        r"pozole|tamale|tamal|sopes|tlacoyo|chalupa|guacamole|"
        r"al pastor|carnita|barbacoa|elote|esquite)\b"
    ),
    "PE": (
        r"\b(ceviche|cebiche|lomo saltado|aj[ií] de gallina|causa lime[ñn]a|"
        r"causa|anticucho|chupe de camarone|rocoto relleno|"
        r"pachamanca|tacu tacu|papa a la huanca[ií]na|"
        r"arroz chaufa|aji de gallina|seco de pollo|escabeche peruano)\b"
    ),
    "AR": (
        r"\b(asado argentino|chimichurri|matambre|milanesa napolitana|"
        r"empanada[s]? de pino|empanada[s]? argentina|locro|"
        r"choripán|provoleta|fugazzeta|alfajor|dulce de leche argentino|"
        r"mate cocido|humita en chala)\b"
    ),
    "BR": (
        r"\b(feijoada|moqueca|p[aã]o de queijo|tapioca brasile[ñn]a|"
        r"tapioca brasile|coxinha|brigadeiro|farofa|"
        r"a[cç]a[ií]|escondidinho|vatap[aá]|caruru|"
        r"baurú|baião de dois|bolinho de bacalhau)\b"
    ),
    "CO": (
        r"\b(arepa colombiana|arepa de huevo|arepa antioque[ñn]a|"
        r"bandeja paisa|ajiaco|sancocho colombiano|"
        r"empanada colombiana|patac[oó]n|chicharr[oó]n paisa|"
        r"changua|mute santandereano|tamal tolimense|lechona)\b"
    ),
    "CL": (
        r"\b(empanada de pino chilena|chacarero|completo chileno|"
        r"pastel de choclo|cazuela chilena|porotos granados|"
        r"curanto|charquic[aá]n|paila marina|chupe de jaiba|"
        r"sopaipilla|pebre|caldillo de congrio)\b"
    ),
    "BO": (
        r"\b(salte[ñn]a|silpancho|pique macho|api boliviano|api con buñuelo|"
        r"charqui|chairo|sajta|fricas[eé]|"
        r"sopa de man[ií]|majadito|saice|"
        r"plato pace[ñn]o|chairo pace[ñn]o|huminta boliviana|"
        r"pukacapa|sopa paraguaya boliviana)\b"
    ),
    "VE": (
        r"\b(arepa venezolana|pabell[oó]n criollo|cachapa|hallaca|"
        r"asado negro|pisca andina|tequeño|"
        r"reina pepiada|cazón|domplina)\b"
    ),
    "EC": (
        r"\b(encebollado|seco de chivo|hornado|fanesca|"
        r"llapingacho|locro de papa ecuatoriano|"
        r"ceviche de chocho|bolón de verde|guatita)\b"
    ),
    "UY": (
        r"\b(chivito|asado uruguayo|chaja|torta frita|"
        r"milanesa al pan uruguaya)\b"
    ),
}


def classify(name_en: str) -> str | None:
    """Return matching country code (e.g. ``MX``) or ``None`` if neutral."""
    text_lower = name_en.lower()
    matches: list[str] = []
    for country, pattern in PATTERNS.items():
        if re.search(pattern, text_lower, re.IGNORECASE):
            matches.append(country)
    # Multi-country matches are rare; pick the first deterministically.
    return matches[0] if matches else None


async def _audit() -> tuple[Counter[str], list[tuple[str, str, str]]]:
    """Scan catalogue. Returns (counter, sample) where sample is
    ``[(id, name_en, new_tag)]`` of first N matches per country.
    """
    counts: Counter[str] = Counter()
    samples: dict[str, list[tuple[str, str, str]]] = {}
    async with session_scope() as s:
        rows = await s.execute(
            text("SELECT id::text, name_en, regions FROM recipes ORDER BY id")
        )
        for r_id, name, _current_regions in rows:
            tag = classify(name)
            new = tag or "world"
            counts[new] += 1
            samples.setdefault(new, [])
            if len(samples[new]) < 5:
                samples[new].append((r_id, name, new))
    flat_samples: list[tuple[str, str, str]] = []
    for k in sorted(samples):
        flat_samples.extend(samples[k])
    return counts, flat_samples


async def _apply() -> int:
    """Apply re-tag. Returns number of rows updated."""
    updated = 0
    async with session_scope() as s:
        rows = (
            await s.execute(text("SELECT id, name_en, regions FROM recipes"))
        ).fetchall()
        for r in rows:
            tag = classify(r.name_en) or "world"
            new_arr = [tag]
            # Compare ignoring whitespace padding (char(5) pads with spaces).
            current = [c.strip() for c in (r.regions or [])]
            if current == [tag]:
                continue
            await s.execute(
                text("UPDATE recipes SET regions = CAST(:r AS char(5)[]) WHERE id = :id"),
                {"r": new_arr, "id": r.id},
            )
            updated += 1
    return updated


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned changes without writing to the DB.",
    )
    args = parser.parse_args()

    print("=== Phase 1: catalogue re-tag by country ===")
    print()

    try:
        counts, samples = await _audit()
    except Exception as exc:  # noqa: BLE001 — CLI top-level
        print(f"audit_failed: {exc}", file=sys.stderr)
        await dispose_engine()
        return 2

    total = sum(counts.values())
    print(f"Total recipes scanned: {total}")
    print()
    print("Distribution by new tag:")
    print(f"  {'tag':<10} {'count':>7}  {'pct':>6}")
    print(f"  {'-' * 10} {'-' * 7}  {'-' * 6}")
    for tag, n in sorted(counts.items(), key=lambda x: -x[1]):
        pct = n * 100 / total if total else 0
        print(f"  {tag:<10} {n:>7}  {pct:>5.1f}%")
    print()
    print("Sample matches per tag:")
    for r_id, name, tag in samples:
        print(f"  [{tag}] {name[:80]}")
    print()

    if args.dry_run:
        print("DRY-RUN: no changes applied.")
        await dispose_engine()
        return 0

    print("Applying changes...")
    updated = await _apply()
    print(f"Updated {updated} rows.")
    await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
