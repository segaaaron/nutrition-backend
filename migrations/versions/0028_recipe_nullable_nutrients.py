"""0028 — Recipe nutrient columns nullable; reset fake zeros to NULL.

Revision: 0028_recipe_nullable_nutrients
Author:   nova-backend-architect
Date:     2026-07-10

Problem fixed
-------------
`recipes.sat_fat_g`, `sugar_g`, `sodium_mg` and `fiber_g` were `INTEGER NOT
NULL DEFAULT 0`. The condition-gate safety filters were written fail-closed —
e.g. FattyLiverGate does ``sat_fat_g IS NOT NULL AND sat_fat_g <= 5`` — on the
assumption that a missing measurement is stored as NULL. The `NOT NULL DEFAULT
0` schema silently turned every un-measured row into "0 g", so:

  - "<= max" gates (sat_fat/sugar/sodium for fatty_liver, etc.) ADMITTED
    un-measured recipes as if they were fat/sugar/sodium free — a safety hole.
  - the ">= min" fiber promotion OVER-EXCLUDED un-measured rows (0 < floor),
    collapsing the candidate pool and forcing repeated recipes.

PROD audit (2026-07-10, 1011 rows) proving the zeros are fake, not measured:
  - sat_fat_g > 0 in only 55 rows; ALL 515 `verified_by` rows are sat_fat=0.
  - sugar_g / sodium_mg > 0 in only 55 rows each (same pattern).
  → For sat_fat/sugar/sodium a 0 is un-measured across the board; reset ALL
    zeros to NULL.
  - fiber_g > 0 in 541 rows, and `verified_by` rows DID populate fiber
    (338/515 > 0). A `verified_by` row with fiber=0 may be a genuine low-fiber
    dish, so only reset fiber zeros on UN-verified rows.

After this migration the fail-closed gates finally do what they say; a real
backfill of the missing values is the follow-up (a NULL now means "measure
me", not "0 g").
"""
from __future__ import annotations

from alembic import op

revision = "0028_recipe_nullable_nutrients"
down_revision = "0027_performance_indexes"
branch_labels = None
depends_on = None

_COLUMNS = ("sat_fat_g", "sugar_g", "sodium_mg", "fiber_g")


def upgrade() -> None:
    # 1. Drop the NOT NULL constraint and the DEFAULT 0 on all four columns.
    #    Dropping the default means a future INSERT that omits the value
    #    stores NULL (unknown) instead of a fake 0 that would pass a gate.
    for col in _COLUMNS:
        op.execute(f"ALTER TABLE recipes ALTER COLUMN {col} DROP NOT NULL")
        op.execute(f"ALTER TABLE recipes ALTER COLUMN {col} DROP DEFAULT")

    # 2. Reset the fake zeros to NULL.
    #    sat_fat/sugar/sodium: every 0 is un-measured (PROD audit) -> NULL all.
    op.execute("UPDATE recipes SET sat_fat_g = NULL WHERE sat_fat_g = 0")
    op.execute("UPDATE recipes SET sugar_g   = NULL WHERE sugar_g   = 0")
    op.execute("UPDATE recipes SET sodium_mg = NULL WHERE sodium_mg = 0")
    #    fiber: verified rows populated fiber, so a verified 0 may be genuine;
    #    only un-verified zeros are treated as un-measured.
    op.execute(
        "UPDATE recipes SET fiber_g = NULL "
        "WHERE fiber_g = 0 AND verified_by IS NULL"
    )


def downgrade() -> None:
    # Restore the pre-migration shape: NULL -> 0, then NOT NULL DEFAULT 0.
    # The unknown/zero distinction is lost on downgrade (acceptable).
    for col in _COLUMNS:
        # noqa justified: `col` is drawn from the hardcoded _COLUMNS tuple,
        # never user input — no injection vector.
        op.execute(f"UPDATE recipes SET {col} = 0 WHERE {col} IS NULL")  # noqa: S608
        op.execute(f"ALTER TABLE recipes ALTER COLUMN {col} SET DEFAULT 0")
        op.execute(f"ALTER TABLE recipes ALTER COLUMN {col} SET NOT NULL")
