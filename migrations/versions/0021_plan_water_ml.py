"""Add water_ml to plans for water_view reconstruction on read.

Revision: 0021_plan_water_ml
Author:   nova-backend-architect
Date:     2026-06-26

Stores the raw daily water target (ml) from nutritional_goals so the
water_view can be rebuilt server-side when iOS fetches the active plan.
Without this column, water_view was always None on read-back from DB.

Nullable: plans created before this migration keep NULL (water_view stays
None for them — acceptable since they predate the water feature).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_plan_water_ml"
down_revision = "0020_plan_band_slot_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("water_ml", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "water_ml")
