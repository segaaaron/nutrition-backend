"""0038 — move the catalog's invariants from scripts into the database.

Revision: 0038_recipe_integrity_constraints
Author:   nova-backend-architect
Date:     2026-08-04

The 2026-08-04 audit found ten classes of wrong data in PROD. Every one was
written by a script that believed it was correct, and every one survived
because the rules it broke lived only in other scripts — advisory checks that
run later, if someone remembers to run them.

This migration makes the structural ones IMPOSSIBLE rather than merely
detectable. A batch that computes kcal wrong, files added sugar above total
sugar, or invents a region tag now fails at INSERT with a named constraint,
in whatever session wrote it, before the bad row exists.

Scope: CONSISTENCY only — relationships that must hold whenever the values are
present. Each constraint is NULL-tolerant, so a row legitimately mid-ingest (or
a focused test fixture inserting `(id, name_en)`) is unaffected. COMPLETENESS —
"every recipe must have nutrition, instructions, an image" — stays in
`scripts/catalog_completeness_audit.py`, because a recipe does pass through an
incomplete state while its components are being written.

The constraints, and the defect each one would have blocked:

  ck_recipes_kcal_atwater        15 snacks stored kcal=130 against an Atwater
                                 value of 263-312. The engine scales portions
                                 by kcal, so those plans served roughly double
                                 what they counted.
  ck_recipes_added_sugar_subset  added_sugar_g is a subset of sugar_g by
                                 definition; exceeding it means the computation
                                 is wrong.
  ck_recipes_nutrition_nonneg    a negative nutrient is always a bug.
  ck_recipes_regions_vocab       nine ISO country codes and a lowercase `bo`
                                 left by an abandoned retag script matched no
                                 market, making those recipes invisible to
                                 every user.
  ck_recipes_rec_conditions_vocab   1,137 recipes carried conditions the engine
  ck_recipes_con_conditions_vocab   deleted in July 2026 (REGLA #0.5.C), and
                                 `recommended_conditions` is serialised
                                 straight into the API response.
  ck_recipe_components_amount_positive   a zero or negative gram amount silently
                                 contributes nothing to the recipe's nutrition.
  ck_recipe_components_name_present      a blank ingredient name cannot resolve
                                 to USDA, so its nutrition is silently lost.

All eight were verified to hold across the 1,611 live rows before this
migration was written, so it applies without a backfill.
"""
from __future__ import annotations

from alembic import op

revision = "0038_recipe_integrity_constraints"
down_revision = "0037_recipes_added_sugar_g"
branch_labels = None
depends_on = None

# (table, constraint_name, expression)
_CONSTRAINTS: list[tuple[str, str, str]] = [
    (
        "recipes",
        "ck_recipes_kcal_atwater",
        # Atwater 4/4/9. Stored kcal must be a function of the stored macros,
        # never an independent number that can drift away from them.
        "kcal IS NULL OR protein_g IS NULL OR carbs_g IS NULL OR fat_g IS NULL"
        " OR kcal = protein_g * 4 + carbs_g * 4 + fat_g * 9",
    ),
    (
        "recipes",
        "ck_recipes_added_sugar_subset",
        "added_sugar_g IS NULL OR sugar_g IS NULL OR added_sugar_g <= sugar_g",
    ),
    (
        "recipes",
        "ck_recipes_nutrition_nonneg",
        "COALESCE(kcal, 0) >= 0 AND COALESCE(protein_g, 0) >= 0"
        " AND COALESCE(carbs_g, 0) >= 0 AND COALESCE(fat_g, 0) >= 0"
        " AND COALESCE(fiber_g, 0) >= 0 AND COALESCE(sugar_g, 0) >= 0"
        " AND COALESCE(added_sugar_g, 0) >= 0 AND COALESCE(sat_fat_g, 0) >= 0"
        " AND COALESCE(sodium_mg, 0) >= 0",
    ),
    (
        "recipes",
        "ck_recipes_regions_vocab",
        # The three markets region_mapper.country_to_region can emit.
        "regions IS NULL OR regions <@ ARRAY['latam','us','ca']::char(5)[]",
    ),
    (
        "recipes",
        "ck_recipes_rec_conditions_vocab",
        "recommended_conditions IS NULL OR recommended_conditions"
        " <@ ARRAY['fatty_liver','pregnancy','lactation']::text[]",
    ),
    (
        "recipes",
        "ck_recipes_con_conditions_vocab",
        "contraindicated_conditions IS NULL OR contraindicated_conditions"
        " <@ ARRAY['fatty_liver','pregnancy','lactation']::text[]",
    ),
    (
        "recipe_components",
        "ck_recipe_components_amount_positive",
        "amount_g IS NULL OR amount_g > 0",
    ),
    (
        "recipe_components",
        "ck_recipe_components_name_present",
        "free_text_name IS NULL OR btrim(free_text_name) <> ''",
    ),
]


def upgrade() -> None:
    for table, name, expression in _CONSTRAINTS:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"  # noqa: S608
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression})"  # noqa: S608
        )


def downgrade() -> None:
    for table, name, _ in _CONSTRAINTS:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"  # noqa: S608
        )
