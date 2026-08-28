"""0053 — unique index on water_logs (user_id, time).

C12 added client-supplied `at` timestamps so multi-device syncs send the same
entry from different devices.  Without a deduplication guard each retry or
cross-device sync inserts a duplicate row, double-counting water intake.

``UNIQUE (user_id, time)`` is valid on a TimescaleDB hypertable because the
partition column (time) is part of the index.  Microsecond precision makes
genuine collisions from two distinct taps statistically impossible; the only
realistic collision is an idempotent retry or a cross-device sync — exactly
the case we want to absorb silently via ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from alembic import op

revision = "0053_water_logs_unique_user_time"
down_revision = "0052_vision_error_slugs_and_tag_i18n"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT CONCURRENTLY: inside Alembic transaction; table is small at this
    # stage so the brief ACCESS SHARE lock is acceptable.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_water_logs_user_time "
        "ON water_logs (user_id, time)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_water_logs_user_time")
