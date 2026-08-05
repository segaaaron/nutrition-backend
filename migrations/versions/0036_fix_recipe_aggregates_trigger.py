"""0036 — stop sync_recipe_aggregates() from zeroing the safety columns.

Revision: 0036_fix_recipe_aggregates_trigger
Author:   nova-backend-architect
Date:     2026-08-04

ROOT CAUSE of the 2026-08-04 catalog audit finding "sodium_mg = 0 on 1,437 of
1,582 active recipes, sat_fat_g = 0 on 1,441, sugar_g = 0 on 1,466".

The trigger recomputed the four safety columns with

    FROM recipe_components rc JOIN foods f ON f.id = rc.food_id

Every row in `recipe_components` carries `food_id IS NULL` (the catalog stores
free-text ingredient names, not `foods` FKs), so the INNER JOIN matched nothing,
the aggregate subquery produced a single all-NULL row, and
`COALESCE(agg.x, 0)` wrote 0 over correct values. Any batch script that
inserted components AFTER setting nutrition silently destroyed it — which is
why every batch since has needed a manual `UPDATE recipes SET ...` afterwards.

Two fixes:

1. **Do not clobber.** When no component of the recipe resolves to a `foods`
   row there is nothing to aggregate, so the trigger must leave the stored
   values alone. `SUM(...)` over an empty set is NULL, so switching the outer
   join to a correlated scalar subquery per column and coalescing to the
   CURRENT value (`r.fiber_g`, not `0`) makes the no-data case a no-op.

2. **Stop truncating.** The old body cast each SUM to `::int` before the
   division had finished accumulating, so 3.6 g of saturated fat stored as 3.
   `ROUND(...)::int` keeps the columns integer (unchanged schema) while
   rounding half-up instead of truncating toward zero.

Reversible: downgrade() restores the previous body verbatim.
"""
from __future__ import annotations

from alembic import op

revision = "0036_fix_recipe_aggregates_trigger"
down_revision = "0035_disliked_ingredients"
branch_labels = None
depends_on = None


_FIXED_BODY = """
CREATE OR REPLACE FUNCTION public.sync_recipe_aggregates()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
    DECLARE
        affected_recipe uuid;
        linked_count    int;
    BEGIN
        affected_recipe := COALESCE(NEW.recipe_id, OLD.recipe_id);

        -- Guard: with no `foods`-linked component there is nothing to
        -- aggregate. Returning early leaves the stored (USDA-computed)
        -- nutrition untouched instead of overwriting it with zeros.
        SELECT COUNT(*) INTO linked_count
          FROM recipe_components rc
         WHERE rc.recipe_id = affected_recipe
           AND rc.food_id IS NOT NULL
           AND rc.amount_g IS NOT NULL;

        IF linked_count = 0 THEN
            RETURN NULL;
        END IF;

        UPDATE recipes r
           SET fiber_g   = COALESCE(agg.fiber,  r.fiber_g),
               sugar_g   = COALESCE(agg.sugar,  r.sugar_g),
               sodium_mg = COALESCE(agg.sodium, r.sodium_mg),
               sat_fat_g = COALESCE(agg.satfat, r.sat_fat_g)
          FROM (
              SELECT
                  ROUND(SUM(f.fiber_g   * rc.amount_g / 100.0))::int AS fiber,
                  ROUND(SUM(f.sugar_g   * rc.amount_g / 100.0))::int AS sugar,
                  ROUND(SUM(f.sodium_mg * rc.amount_g / 100.0))::int AS sodium,
                  ROUND(SUM(f.sat_fat_g * rc.amount_g / 100.0))::int AS satfat
                FROM recipe_components rc
                JOIN foods f ON f.id = rc.food_id
               WHERE rc.recipe_id = affected_recipe
                 AND rc.amount_g IS NOT NULL
          ) agg
         WHERE r.id = affected_recipe;

        RETURN NULL;
    END;
    $function$;
"""

_PREVIOUS_BODY = """
CREATE OR REPLACE FUNCTION public.sync_recipe_aggregates()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
        DECLARE
            affected_recipe uuid;
        BEGIN
            affected_recipe := COALESCE(NEW.recipe_id, OLD.recipe_id);

            UPDATE recipes r
               SET fiber_g   = COALESCE(agg.fiber, 0),
                   sugar_g   = COALESCE(agg.sugar, 0),
                   sodium_mg = COALESCE(agg.sodium_mg, 0),
                   sat_fat_g = COALESCE(agg.sat_fat, 0)
              FROM (
                  SELECT
                      SUM(f.fiber_g    * rc.amount_g / 100.0)::int AS fiber,
                      SUM(f.sugar_g    * rc.amount_g / 100.0)::int AS sugar,
                      SUM(f.sodium_mg  * rc.amount_g / 100.0)::int AS sodium_mg,
                      SUM(f.sat_fat_g  * rc.amount_g / 100.0)::int AS sat_fat
                    FROM recipe_components rc
                    JOIN foods f ON f.id = rc.food_id
                   WHERE rc.recipe_id = affected_recipe
                     AND rc.amount_g IS NOT NULL
              ) agg
             WHERE r.id = affected_recipe;

            RETURN NULL;
        END;
        $function$;
"""


def upgrade() -> None:
    op.execute(_FIXED_BODY)


def downgrade() -> None:
    op.execute(_PREVIOUS_BODY)
