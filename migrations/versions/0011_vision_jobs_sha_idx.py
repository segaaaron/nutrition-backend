"""0011 — vision_jobs partial index for SHA256 dedup cache lookup.

QA CRITICAL-3 fix. The cache short-circuit in `ProcessVisionJob` runs
on the hot path of every photo job (millions/day target). Without a
covering index the query is a seq-scan over the entire `vision_jobs`
table, which makes the "cheap" cache hit slower than re-calling OpenAI.

Index design:
- Partial on `status = 'completed' AND detected_items IS NOT NULL` — only
  rows the cache lookup actually returns.
- DESC on `created_at` so the planner serves the `ORDER BY created_at
  DESC LIMIT 1` from the index without a sort.
- CONCURRENTLY — non-blocking on the live table (vision_jobs already
  has user traffic in dev/staging).

Note on `CONCURRENTLY`: Postgres rejects it inside a transaction. We use
Alembic's official `op.get_context().autocommit_block()` context manager,
which commits the outer migration transaction, runs the DDL in
AUTOCOMMIT, then restarts a fresh transaction. This is the
SQLAlchemy 2.0 + Alembic >=1.13 safe pattern — manually calling
`bind.execution_options(isolation_level="AUTOCOMMIT")` raises
`InvalidRequestError` because the connection already has an autobegun
transaction.

Owner action after merge:
    .venv/bin/python -m alembic upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "0011_vision_jobs_sha_idx"
down_revision = "0010_user_profile_onboarding_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_vision_jobs_sha_recent
            ON vision_jobs (image_sha256, created_at DESC)
            WHERE status = 'completed' AND detected_items IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_vision_jobs_sha_recent"
        )
