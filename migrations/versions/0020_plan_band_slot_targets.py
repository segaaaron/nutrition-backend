"""0020 — plan_days withinBand + kcal_actual; plans slot_targets.

Context
-------
The napkin (2026-06-26) identified two missing invariants in the plan pipeline:

1. **``within_band`` / ``kcal_actual`` on plan_days**: ``create_plan`` now
   portion-scales every meal to hit its slot kcal share. But nothing validated
   that the *day* actually closed near the daily target. Adding ``kcal_actual``
   (sum of scaled meal kcal) and ``within_band`` (actual ± 20 % of target)
   to ``plan_days`` makes the gap observable in SQL/logs and lets iOS surface
   a "today's plan is ~X kcal" badge without recomputing.

2. **``slot_targets`` on plans**: the per-slot kcal/protein share (breakfast:
   500 kcal / 35 g, lunch: 700 kcal / 48 g, …) is computed at generation time
   from ``nutritional_goals`` × ``_SLOT_WEIGHTS``. Persisting it lets iOS show
   target vs actual per slot and avoids re-deriving it from goals + weights at
   read time.

Both columns are nullable: NULL means legacy plan (pre-0020), treat as
unknown / recompute.

Reversibility: downgrade drops all three columns.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_plan_band_slot_targets"
down_revision = "0019_recipe_v3_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # plan_days: actual kcal delivered + band flag
    op.add_column("plan_days", sa.Column("kcal_actual", sa.Integer(), nullable=True))
    op.add_column("plan_days", sa.Column("within_band", sa.Boolean(), nullable=True))

    # plans: per-slot kcal/protein targets as JSONB
    # Example: {"breakfast": {"kcal": 475, "protein_g": 33}, "lunch": {...}, ...}
    op.add_column("plans", sa.Column("slot_targets", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "slot_targets")
    op.drop_column("plan_days", "within_band")
    op.drop_column("plan_days", "kcal_actual")
