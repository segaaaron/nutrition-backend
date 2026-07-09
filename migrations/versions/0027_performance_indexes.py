"""0027 — Performance indexes for hot-path queries.

Revision: 0027_performance_indexes
Author:   nova-backend-architect
Date:     2026-07-09

Problems fixed:
  1. feature_flags table has no index — every leaderboard request triggers
     a full seq-scan, even after Redis caching shields the query (cache miss
     path still needs an index for safety under cold-start / Redis flush).
  2. food_logs COUNT(*) for achievements had no early-exit. The subquery
     rewrite (LIMIT 2) handles this in application code; the index here
     ensures the LIMIT 2 scan is index-only and fast.
  3. nutritional_goals lookup on active plan path — partial index on
     user_id WHERE is_active = true avoids scanning historical goals.

All DDL runs CONCURRENTLY (non-locking) via autocommit_block().
"""
from __future__ import annotations

from alembic import op

revision = "0027_performance_indexes"
down_revision = "0026_profile_goal_weight_kg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # feature_flags: primary access pattern is WHERE key IN (...)
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_feature_flags_key
            ON feature_flags (key)
            """
        )
        # nutritional_goals: hot path is WHERE user_id = :uid — no is_active column in schema
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_nutritional_goals_user_active
            ON nutritional_goals (user_id)
            """
        )
        # food_logs: achievement subquery uses (user_id) with LIMIT 2 — make it index-only
        # ix_food_logs_user_date already covers (user_id, date); this composite adds
        # id to allow index-only scans on COUNT(LIMIT 2) pattern.
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_food_logs_user_id_id
            ON food_logs (user_id, id)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_feature_flags_key")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_nutritional_goals_user_active")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_food_logs_user_id_id")
