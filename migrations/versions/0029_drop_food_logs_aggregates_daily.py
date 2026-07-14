"""0029 — Drop the dead food_logs_aggregates_daily materialised view.

Revision: 0029_drop_food_logs_aggregates_daily
Author:   nova-backend-architect
Date:     2026-07-13

Problem fixed
-------------
`food_logs_aggregates_daily` was created in 0004 as a plain materialised view
``WITH NO DATA`` with the intent of a "daily refresh job" that never existed
(REGLA #3 forbids crons, so nothing ever refreshes it). An unpopulated matview
raises ``ObjectNotInPrerequisiteState: materialized view has not been
populated`` on every SELECT.

Several read paths queried it inside ``try: ... except: pass`` blocks WITHOUT
rolling back, so the failed statement left the request's transaction in an
aborted state; the next query on the same session then raised
``InFailedSQLTransactionError`` and the endpoint returned 500. This poisoned
``GET /logs/food/totals/today``, ``/logs/food/totals/trend`` and the weekly
summary — surfacing to users as "the dashboard breaks after logging a meal".

Root fix
--------
The matview cannot be maintained under the no-cron rule, so it is dead
infrastructure. All three code references were rewritten to aggregate directly
from ``food_logs`` (correct, live data). This migration drops the object so it
can never be referenced again and re-introduce the poison-connection failure.
The unique index ``ux_food_logs_agg_user_day`` is dropped implicitly with the
view.

Reversible: downgrade recreates the view exactly as 0004 defined it.
"""
from __future__ import annotations

from alembic import op

revision = "0029_drop_food_logs_aggregates_daily"
down_revision = "0028_recipe_nullable_nutrients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS food_logs_aggregates_daily")


def downgrade() -> None:
    # Mirror 0004: recreate the plain materialised view + unique index.
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
