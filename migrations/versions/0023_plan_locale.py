"""Add locale to plans for correct water_view reconstruction on read.

Revision: 0023_plan_locale
Author:   nova-backend-architect
Date:     2026-06-26

Stores the user's locale (es/en/pt/fr/de) at plan-creation time so that
_plan_from_model can reconstruct water_view with the correct language.
Without this, iOS users in EN/PT would see the water goal message in Spanish.

Nullable: pre-migration plans default to "es" at read time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_plan_locale"
down_revision = "0022_recipe_contains_meat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("locale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "locale")
