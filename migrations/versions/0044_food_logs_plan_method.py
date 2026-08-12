"""0044 — add 'plan' to log_method_enum for plan-meal food_logs.

When a user completes a plan meal, the MealCompleted handler writes a food_log
row with method='plan' so the history reflects what was actually eaten.
"""

from alembic import op

revision = "0044_food_logs_plan_method"
down_revision = "0043_backfill_name_translations_es"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE log_method_enum ADD VALUE IF NOT EXISTS 'plan'")


def downgrade() -> None:
    # Postgres does not support removing enum values without a full type rebuild.
    # Safe to leave — 'plan' rows would need manual cleanup before downgrading.
    pass
