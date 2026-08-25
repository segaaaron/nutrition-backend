"""0050 — BE-11: user_factor on plan_meals + user_appetite_by_slot table.

user_factor: user-chosen portion multiplier [0.25, 2.0] in 0.25 steps.
  - Stored separately from scaled_factor (engine-computed).
  - Effective macros = plan_meals.kcal * user_factor (computed at read time,
    never stored to avoid divergence on plan re-reads).

food_logs.is_adjusted: true when the food log entry was derived from a
  user_factor != 1.0, for analytics.

user_appetite_by_slot: rolling average of user_factor per (user, meal_time).
  - Fed by PATCH /portion endpoint (Capa 2 of BE-11).
  - Read by create_plan.py (Capa 3) when sample_count >= 3.
  - sample_count used for confidence threshold before pre-calibrating plans.

Revision: 0050_plan_meals_user_factor
"""

from alembic import op

revision = "0050_plan_meals_user_factor"
down_revision = "0049_progress_photos_unique_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE plan_meals
          ADD COLUMN IF NOT EXISTS user_factor NUMERIC(4,2) DEFAULT 1.0 NOT NULL
        """
    )

    op.execute(
        """
        ALTER TABLE food_logs
          ADD COLUMN IF NOT EXISTS is_adjusted BOOLEAN DEFAULT FALSE NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_appetite_by_slot (
            user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            meal_time     TEXT        NOT NULL,
            correction_ratio NUMERIC(6,3) NOT NULL,
            sample_count  INTEGER     NOT NULL DEFAULT 1,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, meal_time)
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_appetite_by_slot_user
            ON user_appetite_by_slot (user_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_appetite_by_slot")
    op.execute("ALTER TABLE food_logs DROP COLUMN IF EXISTS is_adjusted")
    op.execute("ALTER TABLE plan_meals DROP COLUMN IF EXISTS user_factor")
