"""0041 — food_logs.fiber_g and food_logs.sugar_g

Revision: 0041_food_logs_fiber_sugar
Down: 0040_fiber_sodium_targets

fiber_g and sugar_g are computed by macro_grounder, stored in
vision_jobs.detected_items JSONB, and returned in the API — but were never
persisted to food_logs. This migration adds both columns so the micronutrient
data survives the full pipeline and is available for daily summaries and
condition-specific dashboards (fatty_liver, pregnancy, lactation).

Both columns default to 0 so existing rows are unaffected and no backfill is
required.
"""

from alembic import op

revision = "0041_food_logs_fiber_sugar"
down_revision = "0040_fiber_sodium_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE food_logs ADD COLUMN IF NOT EXISTS fiber_g int NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE food_logs ADD COLUMN IF NOT EXISTS sugar_g int NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE food_logs DROP COLUMN IF EXISTS fiber_g")
    op.execute("ALTER TABLE food_logs DROP COLUMN IF EXISTS sugar_g")
