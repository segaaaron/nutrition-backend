"""Restrict the condition columns to the three supported situations.

PERMANENT script. Re-runnable; the audit gates on the same invariants.

CLAUDE.md REGLA #0.5.C closed the medical scope to exactly three situations —
`fatty_liver`, `pregnancy`, `lactation` — and their gates were deleted from the
engine on 2026-07-10. The catalog was never cleaned, so as of 2026-08-04:

  recommended_conditions   diabetes 487, cardiovascular 427, dyslipidemia 161,
                           iron_deficiency_anemia 92, plus the five GOAL values
                           (health/maintain/muscle_gain/weight_loss/weight_gain)
                           stored in a column that is not for goals.
  contraindicated_conditions  ckd 594, diabetes 201, gout 53, hypertension 33,
                           cardiovascular 18, hypercholesterolemia 12,
                           weight_loss 6 — every one a removed condition.

`recommended_conditions` drives no filter; it is serialised straight into the
recipes API response, so `iron_deficiency_anemia` on a recipe reads as a
diagnosis claim to any client — the exact framing REGLA #1 forbids.
`contraindicated_conditions` IS a hard Layer 1 exclusion, but since onboarding
can only ever submit the three supported values, none of the stored values can
match: dead rows that would silently start excluding recipes the moment any of
those strings came back.

Beyond the vocabulary purge, the remaining tags are made coherent with the
engine, because a tag that contradicts the runtime filter is worse than no tag:

  * `fatty_liver` is dropped where the recipe FAILS FattyLiverGate, and ADDED
    where a fatty-liver-authored batch produced a recipe that clears it.
    Claiming a recipe is recommended for fatty liver while the engine refuses
    to serve it is incoherent; so is `nova_liver_v1` shipping 70 recipes for
    this cohort with the tag on none of them.
  * `pregnancy` / `lactation` are dropped where `pregnancy_safe` is not TRUE.

Usage:
    python3 scripts/purge_condition_tags.py --dry-run
    python3 scripts/purge_condition_tags.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

ALLOWED_CONDITIONS = ("fatty_liver", "pregnancy", "lactation")

# FattyLiverGate thresholds — app/plan/domain/condition_gates/fatty_liver.py.
# The 8 g cap is on ADDED sugar (free sugars); total sugar has its own, much
# looser fructose-dose ceiling. Applying the 8 g figure to total sugar was the
# 2026-08-04 defect that stripped the tag from 63 correct recipes.
FL_ADDED_SUGAR_MAX = 8
FL_TOTAL_SUGAR_MAX = 30
FL_SATFAT_MAX, FL_FIBER_MIN, FL_SODIUM_MAX = 5, 3, 600

# Batches authored specifically for the fatty-liver cohort. A recipe from one
# of these that passes the gate SHOULD carry the tag: `nova_liver_v1` (70) and
# `qa_fix_fattyliver_snacks_20260720` (14) were never tagged at all, so they
# were invisible in every condition-filtered catalog view even though the
# engine would happily serve them.
FATTY_LIVER_BATCH_PATTERN = "%liver%"


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
            SELECT id, name_en,
                   COALESCE(recommended_conditions, '{}') AS rec,
                   COALESCE(contraindicated_conditions, '{}') AS con,
                   sugar_g, added_sugar_g, sat_fat_g, fiber_g, sodium_mg,
                   pregnancy_safe,
                   (source_batch ILIKE $1) AS fatty_liver_batch
              FROM recipes ORDER BY id
        """, FATTY_LIVER_BATCH_PATTERN)

        dropped_vocab, dropped_incoherent = Counter(), Counter()
        added_coherent: Counter = Counter()
        updates = []
        for r in recipes:
            rec = set(r["rec"])
            con = set(r["con"])

            for value in rec - set(ALLOWED_CONDITIONS):
                dropped_vocab[f"rec:{value}"] += 1
            for value in con - set(ALLOWED_CONDITIONS):
                dropped_vocab[f"con:{value}"] += 1

            new_rec = rec & set(ALLOWED_CONDITIONS)
            new_con = con & set(ALLOWED_CONDITIONS)

            passes_fl = (
                r["added_sugar_g"] is not None
                and r["added_sugar_g"] <= FL_ADDED_SUGAR_MAX
                and (r["sugar_g"] is None or r["sugar_g"] <= FL_TOTAL_SUGAR_MAX)
                and r["sat_fat_g"] is not None and r["sat_fat_g"] <= FL_SATFAT_MAX
                and r["fiber_g"] is not None and r["fiber_g"] >= FL_FIBER_MIN
                and r["sodium_mg"] is not None and r["sodium_mg"] <= FL_SODIUM_MAX
            )
            if "fatty_liver" in new_rec and not passes_fl:
                new_rec.discard("fatty_liver")
                dropped_incoherent["fatty_liver (fails gate)"] += 1
            # Self-healing the other way: a recipe authored for this cohort that
            # clears the gate should say so. Otherwise the catalog under-reports
            # its own fatty-liver coverage.
            elif (r["fatty_liver_batch"] and passes_fl
                  and "fatty_liver" not in new_rec):
                new_rec.add("fatty_liver")
                added_coherent["fatty_liver (authored batch, passes gate)"] += 1
            if r["pregnancy_safe"] is not True:
                for tag in ("pregnancy", "lactation"):
                    if tag in new_rec:
                        new_rec.discard(tag)
                        dropped_incoherent[f"{tag} (not pregnancy_safe)"] += 1

            if new_rec != rec or new_con != con:
                updates.append((r, sorted(new_rec), sorted(new_con)))

        print(f"recipes            : {len(recipes)}")
        print(f"recipes changing   : {len(updates)}")

        print("\n--- values dropped (outside the supported vocabulary) ---")
        for value, n in dropped_vocab.most_common():
            print(f"  {value:<40} {n:>5}")

        print("\n--- tags dropped for contradicting the engine ---")
        for value, n in dropped_incoherent.most_common():
            print(f"  {value:<40} {n:>5}")

        print("\n--- tags added (authored for the cohort and clears the gate) ---")
        for value, n in added_coherent.most_common():
            print(f"  {value:<40} {n:>5}")
        if not added_coherent:
            print("  none")

        print("\n--- resulting pools ---")
        for cond in ALLOWED_CONDITIONS:
            n = sum(1 for _, rec, _ in updates if cond in rec)
            kept = sum(1 for r in recipes
                       if cond in set(r["rec"])
                       and not any(r["id"] == u[0]["id"] for u in updates))
            print(f"  {cond:<14} {n + kept}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        async with conn.transaction():
            for r, rec, con in updates:
                await conn.execute(
                    "UPDATE recipes SET recommended_conditions = $1::text[], "
                    "contraindicated_conditions = $2::text[] WHERE id = $3",
                    rec, con, r["id"])

        print(f"\nAPPLIED — {len(updates)} recipes updated.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
