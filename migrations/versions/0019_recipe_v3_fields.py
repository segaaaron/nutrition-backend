"""0019 — Recipe v3 catalog fields: cuisine, dish_family, scale bounds.

Context
-------
The v3 catalog (``data/meals/nova_meals_v3.json``) carries per-recipe metadata
that the DB schema never had: ``cuisine``, ``dish_family``, and per-recipe
portion-scaling bounds (``scale_min`` / ``scale_max``).

* ``cuisine`` (e.g. "andina", "mexicana") — cultural cluster for future
  Layer3 diversity filtering and user-facing display.
* ``dish_family`` (e.g. "api_con_pan", "lomo_saltado") — dish-family
  grouping so same-family dishes can be de-prioritised across the week.
* ``scale_min`` / ``scale_max`` — per-recipe safe portion range.
  ``create_plan`` uses these instead of the global (0.5 / 2.0) fallback
  when present, so lightweight dishes (drinks, soups) aren't stretched
  beyond what the recipe physically allows, and dense dishes aren't
  shrunk to a nutritional nothing.

All columns are nullable: legacy recipes that predate v3 keep NULL; the
global bounds remain as fallback in ``create_plan``.

Reversibility: downgrade drops all four columns.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_recipe_v3_fields"
down_revision = "0018_plan_meal_scaled_factor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("cuisine", sa.Text(), nullable=True))
    op.add_column("recipes", sa.Column("dish_family", sa.Text(), nullable=True))
    op.add_column("recipes", sa.Column("scale_min", sa.Numeric(5, 3), nullable=True))
    op.add_column("recipes", sa.Column("scale_max", sa.Numeric(5, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "scale_max")
    op.drop_column("recipes", "scale_min")
    op.drop_column("recipes", "dish_family")
    op.drop_column("recipes", "cuisine")
