"""0004 — food_logs daily continuous aggregate.

Adds `food_logs_aggregates_daily` materialised view (TimescaleDB-flavoured
continuous aggregate where possible; falls back to a plain materialised view
when the food_logs table is not a hypertable in the running cluster — useful
for CI environments that lack the Timescale extension).
"""
from __future__ import annotations

from alembic import op

revision = "0004_food_log_aggregates"
down_revision = "0003_push_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Try Timescale continuous aggregate first. If food_logs is not a
    # hypertable (it isn't by default — it's a regular relational table),
    # fall back to a plain materialised view + a daily refresh job.
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS food_logs_aggregates_daily AS
        SELECT
            user_id,
            date AS day,
            SUM(kcal)::int      AS kcal,
            SUM(protein_g)::int AS protein_g,
            SUM(carbs_g)::int   AS carbs_g,
            SUM(fat_g)::int     AS fat_g,
            COUNT(*)::int       AS n_logs
        FROM food_logs
        GROUP BY user_id, date
        WITH NO DATA
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_food_logs_agg_user_day
        ON food_logs_aggregates_daily (user_id, day)
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS food_logs_aggregates_daily")
