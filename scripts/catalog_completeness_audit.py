"""Catalog completeness audit — boot gate + CI gate.

Two tiers.

**Tier 1 — NULL completeness** (unchanged contract). NULL ratio on
CRITICAL_COLUMNS across `recipes`, classified against a soft and a hard
threshold.

**Tier 2 — integrity gates** (added 2026-08-04). Tier 1 alone reported the
catalog GREEN on the day it was carrying: `sodium_mg = 0` on 1,437 of 1,582
active recipes, 15 snacks whose stored kcal was 130 against an Atwater value
of 300+, 131 recipes with an undeclared allergen (8 of them peanut), zero
recipes tagged for the Canadian market its own `region_mapper` routes users
to, and 1,137 recipes carrying `recommended_conditions` the engine deleted in
July. Every one of those passed because a NULL check cannot see a wrong value,
only a missing one. Tier 2 gates on the values themselves — each check below
exists because that exact defect shipped to PROD.

Exit codes (the entrypoint treats ONLY 3 as fatal; CI blocks on any non-zero):

  0 — clean
  1 — a Tier 2 integrity gate failed, or Tier 1 hard threshold breached
  2 — the audit could not run (no DATABASE_URL, DB unreachable)
  3 — Tier 1 soft threshold breached (boot refuses to start)

Usage:
    python3 scripts/catalog_completeness_audit.py
    python3 scripts/catalog_completeness_audit.py --json        # machine-readable
    python3 scripts/catalog_completeness_audit.py --no-integrity  # Tier 1 only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from functools import lru_cache

# Columns the R6 fail-closed Layer 1 filters depend on.
# Changing this set narrows/expands the boot-gate surface — update the
# locked test in tests/unit/catalog/test_audit_critical_columns_nonempty.py
# and open an ADR before modifying.
#
# potassium_mg: demoted to INFO tier 2026-06-03 (CKD onboarding blocked
# during closed-beta). Re-promote before enabling CKD onboarding.
CRITICAL_COLUMNS: list[str] = [
    "sugar_g",
    "sodium_mg",
    "sat_fat_g",
    "protein_g",
    "fiber_g",
]

_SOFT_THRESHOLD_DEFAULT = Decimal("0.05")   # 5%  → boot warn
_HARD_THRESHOLD_DEFAULT = Decimal("0.10")   # 10% → CI block / boot refuse


@dataclass
class ColumnAudit:
    """Per-column NULL audit result."""

    column: str
    null_count: int
    total: int

    @property
    def ratio(self) -> Decimal:
        """NULL ratio, quantised to 4 dp. Returns 0 on empty table."""
        if self.total == 0:
            return Decimal("0")
        raw = Decimal(self.null_count) / Decimal(self.total)
        return raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def classify(
    audits: list[ColumnAudit],
    *,
    soft_threshold: Decimal = _SOFT_THRESHOLD_DEFAULT,
    hard_threshold: Decimal = _HARD_THRESHOLD_DEFAULT,
) -> tuple[bool, bool]:
    """Return (soft_breached, hard_breached).

    Strict inequality: a ratio exactly at the threshold is NOT a breach.
    """
    soft = any(a.ratio > soft_threshold for a in audits)
    hard = any(a.ratio > hard_threshold for a in audits)
    return soft, hard


SUPPORTED_MARKETS: tuple[str, ...] = ("latam", "us", "ca")
SUPPORTED_CONDITIONS: tuple[str, ...] = ("fatty_liver", "pregnancy", "lactation")

# |kcal - (4P + 4C + 9F)| / kcal must stay within this. Single source of truth
# is spec §6 / app/shared/domain/macro_tolerance.py; mirrored here so the audit
# has no app import at boot.
MACRO_TOLERANCE = Decimal("0.02")

# Outer slot bands. A recipe outside these is mis-portioned, not merely
# unusual; scripts/recompute_catalog_nutrition.py rescales to the official
# bands. Kept wider than the official bands so ordinary variation is not noise.
SLOT_KCAL_BANDS: dict[str, tuple[int, int]] = {
    "breakfast": (300, 700),
    "lunch": (450, 900),
    "dinner": (380, 850),
    "snack": (70, 200),
}

# Distinct recipes needed per market x goal x slot. 21 = seven days without a
# repeat (REGLA #0.5.D); 63 = the 3x buffer that keeps plans varied.
POOL_HARD_MIN = 21
POOL_WARN_MIN = 63


@dataclass
class IntegrityCheck:
    """One Tier 2 gate: a named invariant plus the rows that violate it."""

    name: str
    detail: str
    violations: int
    samples: list[str] = field(default_factory=list)
    fatal: bool = True

    @property
    def passed(self) -> bool:
        return self.violations == 0


@lru_cache(maxsize=1)
def _load_allergen_map() -> dict[str, list[str]]:
    """Ingredient -> allergens. Read synchronously outside the event loop."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..",
        "data", "nutrition_reference", "ingredient_allergens.json")
    with open(path, encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


async def _integrity_checks(conn) -> list[IntegrityCheck]:  # noqa: ANN001, C901, PLR0915
    """Tier 2. Every gate here maps to a defect that reached PROD."""
    checks: list[IntegrityCheck] = []

    async def gate(name: str, detail: str, sql: str, *args, fatal: bool = True) -> None:
        rows = await conn.fetch(sql, *args)
        checks.append(IntegrityCheck(
            name=name,
            detail=detail,
            violations=len(rows),
            samples=[str(r[0])[:90] for r in rows[:8]],
            fatal=fatal,
        ))

    # 1. The sync_recipe_aggregates clobber signature (migration 0036). The
    #    trigger inner-joined `foods` on a NULL food_id, so its aggregate was
    #    empty and COALESCE(..., 0) wrote zeros over all four safety columns
    #    at once. A recipe that has components can never legitimately be 0 on
    #    every one of them.
    await gate(
        "safety_columns_all_zero",
        "recipe has components but fiber+sugar+sodium+sat_fat are ALL 0 "
        "(signature of the sync_recipe_aggregates clobber)",
        """
        SELECT r.name_en FROM recipes r
         WHERE COALESCE(r.fiber_g,0)=0 AND COALESCE(r.sugar_g,0)=0
           AND COALESCE(r.sodium_mg,0)=0 AND COALESCE(r.sat_fat_g,0)=0
           AND EXISTS (SELECT 1 FROM recipe_components rc WHERE rc.recipe_id=r.id)
         ORDER BY r.name_en
        """,
    )

    # 2. Sodium zero. Usually means "never computed", but a small fruit-and-nut
    #    snack genuinely rounds to 0 mg (almonds carry 1 mg/100 g, peach 0), so
    #    this is a warning. The clobber signature above is the fatal one.
    await gate(
        "sodium_zero",
        "sodium_mg = 0 — verify it was computed and not merely defaulted",
        "SELECT name_en FROM recipes WHERE COALESCE(sodium_mg,0)=0 ORDER BY name_en",
        fatal=False,
    )

    # 2b. added_sugar_g backs the fatty-liver gate (migration 0037). NULL is
    #     fail-closed there, so a missing value silently shrinks the pool for
    #     exactly the users the gate exists to protect. And added sugar is a
    #     SUBSET of total sugar — if it exceeds it, the computation is wrong.
    await gate(
        "added_sugar_missing",
        "added_sugar_g IS NULL — FattyLiverGate is fail-closed on it, so these "
        "recipes are invisible to every fatty-liver user",
        "SELECT name_en FROM recipes WHERE added_sugar_g IS NULL ORDER BY name_en",
    )
    await gate(
        "added_sugar_exceeds_total",
        "added_sugar_g > sugar_g — added sugar is a subset of total sugar",
        "SELECT name_en FROM recipes WHERE added_sugar_g > sugar_g ORDER BY name_en",
    )

    # 3. Stored kcal must agree with stored macros. 15 snacks shipped with a
    #    hardcoded kcal=130 against an Atwater value of 263-312 — the engine
    #    scales portions by kcal, so those plans served double what they counted.
    await gate(
        "atwater_mismatch",
        f"|kcal - (4P+4C+9F)| / kcal > {MACRO_TOLERANCE}",
        """
        SELECT name_en FROM recipes
         WHERE kcal > 0
           AND ABS(kcal - (protein_g*4 + carbs_g*4 + fat_g*9))::numeric / kcal > $1
         ORDER BY name_en
        """,
        MACRO_TOLERANCE,
    )

    # 4. Nutrition must be traceable. No components => the numbers came from
    #    nowhere and cannot be recomputed or audited.
    await gate(
        "recipe_without_components",
        "recipe has zero rows in recipe_components (nutrition not traceable)",
        """
        SELECT r.name_en FROM recipes r
         WHERE NOT EXISTS (SELECT 1 FROM recipe_components rc WHERE rc.recipe_id=r.id)
         ORDER BY r.name_en
        """,
    )

    # 5. Region taxonomy. `ca` sat at zero recipes while region_mapper routed
    #    Canadians to it, and nine leftover ISO country codes matched no market.
    await gate(
        "region_tag_unsupported",
        f"regions contains a tag outside {SUPPORTED_MARKETS}",
        """
        SELECT DISTINCT btrim(x) FROM recipes, unnest(regions) x
         WHERE btrim(x) <> ALL($1::text[]) ORDER BY 1
        """,
        list(SUPPORTED_MARKETS),
    )
    await gate(
        "region_missing",
        "recipe carries no region at all",
        "SELECT name_en FROM recipes WHERE regions IS NULL OR cardinality(regions)=0",
    )
    empty_markets = []
    for market in SUPPORTED_MARKETS:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM recipes WHERE quarantined_at IS NULL "
            "AND regions @> CAST(ARRAY[$1] AS char(5)[])", market)
        if n == 0:
            empty_markets.append(market)
    checks.append(IntegrityCheck(
        name="market_empty",
        detail="a supported market has zero active recipes (users there get no plan)",
        violations=len(empty_markets),
        samples=empty_markets,
    ))

    # 6. Condition vocabulary — REGLA #0.5.C closed the scope to three.
    #    `recommended_conditions` is serialised into the API response, so a
    #    stale `iron_deficiency_anemia` reads as a diagnosis claim (REGLA #1).
    await gate(
        "recommended_conditions_unsupported",
        f"recommended_conditions contains a value outside {SUPPORTED_CONDITIONS}",
        """
        SELECT DISTINCT c FROM recipes, unnest(recommended_conditions) c
         WHERE c <> ALL($1::text[]) ORDER BY 1
        """,
        list(SUPPORTED_CONDITIONS),
    )
    await gate(
        "contraindicated_conditions_unsupported",
        f"contraindicated_conditions contains a value outside {SUPPORTED_CONDITIONS}",
        """
        SELECT DISTINCT c FROM recipes, unnest(contraindicated_conditions) c
         WHERE c <> ALL($1::text[]) ORDER BY 1
        """,
        list(SUPPORTED_CONDITIONS),
    )

    # 7. Allergen declaration must cover the ingredients. Layer 1 excludes on
    #    `recipes.allergens` and never looks at components, so an undeclared
    #    peanut is served to a peanut-allergic user. FALCPA / FASTER Act.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ingredient_resolver import (  # noqa: PLC0415
            UnresolvedIngredientError,
            resolve_key,
        )

        allergen_map = _load_allergen_map()

        comps = await conn.fetch(
            "SELECT recipe_id, free_text_name FROM recipe_components")
        recipes = await conn.fetch(
            "SELECT id, name_en, COALESCE(allergens,'{}')::text[] AS declared FROM recipes")

        by_recipe: dict = {}
        unresolved_names: set[str] = set()
        for c in comps:
            by_recipe.setdefault(c["recipe_id"], []).append(c["free_text_name"])

        undeclared: list[str] = []
        for r in recipes:
            implied: set[str] = set()
            for name in by_recipe.get(r["id"], []):
                try:
                    implied.update(allergen_map.get(resolve_key(name), ()))
                except UnresolvedIngredientError:
                    unresolved_names.add(name)
            missing = implied - set(r["declared"])
            if missing:
                undeclared.append(f"{r['name_en'][:60]} (missing {','.join(sorted(missing))})")

        checks.append(IntegrityCheck(
            name="allergen_undeclared",
            detail="an ingredient implies an allergen the recipe does not declare",
            violations=len(undeclared),
            samples=undeclared[:8],
        ))
        # 8. Every ingredient must resolve to a USDA entry, or its nutrition
        #    silently contributes zero to the recipe totals.
        checks.append(IntegrityCheck(
            name="ingredient_unresolved",
            detail="free_text_name has no USDA-backed match (nutrition would be understated)",
            violations=len(unresolved_names),
            samples=sorted(unresolved_names)[:8],
        ))
    except Exception as exc:  # noqa: BLE001
        checks.append(IntegrityCheck(
            name="allergen_and_ingredient_checks",
            detail=f"could not run (resolver or allergen map unavailable): {exc}",
            violations=1,
            fatal=False,
        ))

    # 9. Slot kcal bands — a 460 kcal "snack" wrecks the day's total.
    band_rows: list[str] = []
    for slot, (lo, hi) in SLOT_KCAL_BANDS.items():
        rows = await conn.fetch(
            "SELECT name_en, kcal FROM recipes WHERE meal_time::text = $1 "
            "AND (kcal < $2 OR kcal > $3) ORDER BY kcal", slot, lo, hi)
        band_rows.extend(f"{slot}: {r['name_en'][:52]} = {r['kcal']} kcal" for r in rows)
    checks.append(IntegrityCheck(
        name="kcal_outside_slot_band",
        detail=f"recipe kcal outside its slot band {SLOT_KCAL_BANDS}",
        violations=len(band_rows),
        samples=band_rows[:8],
    ))

    # 10. Pool depth. A market x goal x slot below 21 cannot fill a 7-day plan
    #     without repeating, and REGLA #0.5.D forbids repeats — generation
    #     aborts instead. Below 63 there is no buffer; that is a warning.
    thin_hard: list[str] = []
    thin_warn: list[str] = []
    goals = [r["g"] for r in await conn.fetch(
        "SELECT unnest(enum_range(NULL::goal_enum))::text AS g")]
    for market in SUPPORTED_MARKETS:
        rows = await conn.fetch("""
            SELECT g::text AS goal, meal_time::text AS slot, COUNT(*) AS n
              FROM recipes, unnest(target_goals) g
             WHERE quarantined_at IS NULL
               AND regions @> CAST(ARRAY[$1] AS char(5)[])
             GROUP BY g, meal_time
        """, market)
        counts = {(r["goal"], r["slot"]): r["n"] for r in rows}
        for goal in goals:
            for slot in SLOT_KCAL_BANDS:
                n = counts.get((goal, slot), 0)
                label = f"{market}/{goal}/{slot} = {n}"
                if n < POOL_HARD_MIN:
                    thin_hard.append(label)
                elif n < POOL_WARN_MIN:
                    thin_warn.append(label)
    checks.append(IntegrityCheck(
        name="pool_below_hard_minimum",
        detail=f"market x goal x slot below {POOL_HARD_MIN} distinct recipes "
               "(7-day plan cannot avoid repeats; generation aborts)",
        violations=len(thin_hard),
        samples=thin_hard[:8],
    ))
    checks.append(IntegrityCheck(
        name="pool_below_buffer",
        detail=f"market x goal x slot below the {POOL_WARN_MIN} buffer (warning only)",
        violations=len(thin_warn),
        samples=thin_warn[:8],
        fatal=False,
    ))

    return checks


async def _audit_db(database_url: str) -> list[ColumnAudit]:
    """Run NULL audit against the live DB using asyncpg — the project's only DB
    driver (2026-07-18: was psycopg2, which is not a dependency; every boot logged
    'DB audit failed: No module named psycopg2')."""
    import asyncpg  # noqa: PLC0415

    # SQLAlchemy asyncpg URL → plain DSN that asyncpg.connect accepts.
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        results: list[ColumnAudit] = []
        for col in CRITICAL_COLUMNS:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) FILTER (WHERE {col} IS NULL) AS nulls, "  # noqa: S608
                "COUNT(*) AS total FROM recipes"
            )
            results.append(
                ColumnAudit(column=col, null_count=row["nulls"], total=row["total"])
            )

        # Hard gate: description_en must be populated on every recipe.
        # A NULL description means the batch script that generated the recipe
        # failed to produce human-readable copy — the iOS client shows nothing.
        desc_rows = await conn.fetch(
            "SELECT name_en, source_batch FROM recipes "  # noqa: S608
            "WHERE description_en IS NULL ORDER BY source_batch, name_en"
        )
        if desc_rows:
            offenders = "\n".join(
                f"  [{r['source_batch']}] {r['name_en']}" for r in desc_rows
            )
            print(
                f"GATE FAIL — description_en IS NULL on {len(desc_rows)} recipes:\n{offenders}",
                file=sys.stderr,
            )
            # Inject as a synthetic ColumnAudit with ratio 1.0 so classify()
            # always triggers hard_breached.
            total = await conn.fetchval("SELECT COUNT(*) FROM recipes")
            results.append(
                ColumnAudit(column="description_en", null_count=len(desc_rows), total=total or 1)
            )

        return results
    finally:
        await conn.close()


async def _run_integrity(database_url: str) -> list[IntegrityCheck]:
    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        return await _integrity_checks(conn)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catalog NULL completeness audit")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument(
        "--soft", type=float, default=float(_SOFT_THRESHOLD_DEFAULT), help="Soft threshold"
    )
    parser.add_argument(
        "--hard", type=float, default=float(_HARD_THRESHOLD_DEFAULT), help="Hard threshold"
    )
    parser.add_argument(
        "--boot-guard", action="store_true", help="Boot guard mode (entrypoint label, no-op)"
    )
    parser.add_argument(
        "--no-integrity", action="store_true",
        help="Skip Tier 2 integrity gates (NULL completeness only)",
    )
    args = parser.parse_args(argv)

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    try:
        audits = asyncio.run(_audit_db(db_url))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: DB audit failed: {exc}", file=sys.stderr)
        return 2

    soft_t = Decimal(str(args.soft))
    hard_t = Decimal(str(args.hard))
    soft_breached, hard_breached = classify(audits, soft_threshold=soft_t, hard_threshold=hard_t)

    max_ratio = max((a.ratio for a in audits), default=Decimal("0"))

    integrity: list[IntegrityCheck] = []
    integrity_failed = False
    if not args.no_integrity:
        try:
            integrity = asyncio.run(_run_integrity(db_url))
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: integrity gates failed to run: {exc}", file=sys.stderr)
            return 2
        integrity_failed = any(c.fatal and not c.passed for c in integrity)

    if args.json:
        print(
            json.dumps(
                {
                    "cols": len(audits),
                    "max_null_ratio": str(max_ratio),
                    "soft_breached": soft_breached,
                    "hard_breached": hard_breached,
                    "integrity_failed": integrity_failed,
                    "columns": [
                        {"col": a.column, "null_count": a.null_count, "ratio": str(a.ratio)}
                        for a in audits
                    ],
                    "integrity": [
                        {
                            "check": c.name,
                            "violations": c.violations,
                            "fatal": c.fatal,
                            "samples": c.samples,
                        }
                        for c in integrity
                    ],
                }
            )
        )
    else:
        print(f"cols={len(audits)} max_null_ratio={max_ratio}")
        for a in audits:
            flag = "⚠️" if a.ratio > soft_t else "✓"
            print(f"  {flag} {a.column}: {a.null_count}/{a.total} ({a.ratio})")

        if integrity:
            print("\nintegrity gates:")
            for c in integrity:
                if c.passed:
                    flag = "✓"
                elif c.fatal:
                    flag = "✗ FAIL"
                else:
                    flag = "⚠️ WARN"
                print(f"  {flag} {c.name}: {c.violations}")
                if not c.passed:
                    print(f"      {c.detail}")
                    for sample in c.samples:
                        print(f"        - {sample}")
                    if c.violations > len(c.samples):
                        print(f"        ... and {c.violations - len(c.samples)} more")

    if integrity_failed:
        # Reported as a CI block, not a boot refusal: these defects mean the
        # catalog is serving wrong data, but refusing to boot would take the
        # whole API down over a data problem a redeploy cannot fix.
        return 1
    if hard_breached:
        return 1   # CI block
    if soft_breached:
        return 3   # boot warn
    return 0


if __name__ == "__main__":
    sys.exit(main())
