"""Profile: add goal_weight_kg column.

Revision: 0026_profile_goal_weight_kg
Author:   nova-api-expert
Date:     2026-07-08

Adds `goal_weight_kg NUMERIC(5,2)` to `user_profiles` so users can persist
a numeric weight target (separate from the qualitative `goal` enum).

iOS uses this to:
  - Display the "Target" stat on the Profile screen.
  - Render the "Tu progreso" card (current vs target weight ratio).

The column is nullable because existing users have no target weight set yet.
It is exposed via PATCH /me (goal_weight_kg field) and GET /me (ProfileResponse).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_profile_goal_weight_kg"
down_revision = "0025_recipe_excluded_countries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("goal_weight_kg", sa.Numeric(5, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "goal_weight_kg")
