"""0035 — user_profiles.disliked_ingredients (taste-preference exclusion).

Revision: 0035_disliked_ingredients
Author:   nova-backend-architect
Date:     2026-07-20

Adds a text[] column holding free-text ingredients the user does not want in
their plan ("no me gusta el brócoli"). Delivers the onboarding promise "NOVA
excluirá los alimentos que no comes" beyond the vegan/vegetarian flag.

Layer 1 uses it as a RELAXABLE preference (dropped first in the fallback chain
before region/meal-time) — never a safety filter, so it can never abort plan
generation. Safety filters (allergens, condition gates, landlocked) stay hard.

NOT NULL with server_default '{}' so every existing row is a no-op ('nothing
disliked'). Idempotent add.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0035_disliked_ingredients"
down_revision = "0034_generic_latam_recipe_names"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    cols = [c["name"] for c in inspect(op.get_bind()).get_columns(table)]
    return column in cols


def upgrade() -> None:
    # Idempotent: safe if the column was pre-provisioned out-of-band.
    if not _has_column("user_profiles", "disliked_ingredients"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "disliked_ingredients",
                ARRAY(sa.Text()),
                nullable=False,
                server_default="{}",
            ),
        )


def downgrade() -> None:
    if _has_column("user_profiles", "disliked_ingredients"):
        op.drop_column("user_profiles", "disliked_ingredients")
