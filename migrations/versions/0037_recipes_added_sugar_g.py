"""0037 — recipes.added_sugar_g, so the fatty-liver gate measures what it claims.

Revision: 0037_recipes_added_sugar_g
Author:   nova-nutrition-algorithms-expert
Date:     2026-08-04

`FattyLiverGate` filters on `sugar_g <= 8` and justifies the threshold in its
own docstring as "added/free sugars drive de novo lipogenesis". But `sugar_g`
stores TOTAL sugars, and the codebase already knew the difference —
`app/plan/application/taste_profile.py` says about the same column:

    the catalog's sugar_g column includes natural fruit sugars (total sugars,
    not added), so a hard gate would wrongly exclude healthy fruit dishes

The contradiction was invisible while the 2026-08-04 trigger defect left
`sugar_g = 0` on 1,466 recipes. Once real values landed, the gate began
excluding 53 fatty-liver recipes that are yogurt-oat-fruit breakfasts whose
sugar is entirely intrinsic — nutritionally appropriate for NAFLD, rejected by
a threshold meant for free sugars.

This column carries the free-sugar figure so the gate can test the quantity its
thresholds were derived from (WHO 2015 free sugars <10% of energy; AASLD 2023).
It is computed by `scripts/recompute_catalog_nutrition.py` from the
added-sugar ingredient set in
`data/nutrition_reference/ingredient_added_sugar.json`.

INTEGER, matching every other macro column, so the mobile response schemas
(`int | None`) need no contract change.

Nullable with no backfill value: the recompute populates it, and the gate is
R6 fail-closed on NULL (a recipe whose free sugars are unknown is not served to
a fatty-liver user).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0037_recipes_added_sugar_g"
down_revision = "0036_fix_recipe_aggregates_trigger"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("recipes", "added_sugar_g"):
        op.add_column("recipes", sa.Column("added_sugar_g", sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column("recipes", "added_sugar_g"):
        op.drop_column("recipes", "added_sugar_g")
