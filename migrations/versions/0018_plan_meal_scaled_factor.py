"""0018 — plan_meals.scaled_factor for portion scaling.

``create_plan`` now scales the picked recipe's portion so each meal hits its
slot kcal share. Before this, each ``plan_meal`` carried the recipe's *native*
kcal/macros, which rarely equal the slot target — the day drifted (the old
``meals_per_day`` bug delivered ~60 % of target; even after that fix the day
only approximated, never closed).

``scaled_factor`` is the multiplier applied to the recipe's native macros for
this meal. **iOS MUST multiply the displayed ingredient amounts by it** so the
shown portion matches the shown kcal — otherwise the recipe reads with native
amounts but a scaled kcal number (display mismatch). ``1.0`` = unscaled,
``NULL`` = legacy row (treat as 1.0).

Reversibility: downgrade drops the column.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_plan_meal_scaled_factor"
down_revision = "0017_recipe_diet_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_meals", sa.Column("scaled_factor", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("plan_meals", "scaled_factor")
