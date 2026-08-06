"""0040 — add fiber_target_g and sodium_target_mg to nutritional_goals.

Revision: 0040_fiber_sodium_targets
Author:   nova-backend-architect
Date:     2026-08-06

Two new columns in `nutritional_goals` so the app can show progress bars
against daily targets for fiber and sodium — not just kcal/protein/water.

  fiber_target_g:   14 g per 1,000 kcal (Dietary Guidelines for Americans
                    2020-2025, Part D §2 — Dietary Fiber). Backfilled from
                    the midpoint of kcal_min/kcal_max on existing rows.

  sodium_target_mg: 2,000 mg/day general population (WHO 2023 sodium
                    reduction guideline: <2 g/day). Column carries a fixed
                    default; future work can vary by conditions
                    (hypertension → 1,500 mg) when that condition gate
                    is re-enabled by the owner.

Downgrade: DROP COLUMN — safe, no FK dependencies.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0040_fiber_sodium_targets"
down_revision = "0039_meal_time_five_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nutritional_goals",
        sa.Column("fiber_target_g", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "nutritional_goals",
        sa.Column("sodium_target_mg", sa.Integer(), nullable=False, server_default="2000"),
    )
    # Backfill fiber for all existing rows using 14 g / 1,000 kcal on the
    # kcal midpoint.  GREATEST(1, …) prevents a zero target on legacy rows
    # that may have had unusually low kcal values.
    op.execute(
        """
        UPDATE nutritional_goals
           SET fiber_target_g = GREATEST(
               1,
               ROUND(((kcal_min + kcal_max) / 2.0) / 1000.0 * 14)::smallint
           )
        """
    )


def downgrade() -> None:
    op.drop_column("nutritional_goals", "sodium_target_mg")
    op.drop_column("nutritional_goals", "fiber_target_g")
