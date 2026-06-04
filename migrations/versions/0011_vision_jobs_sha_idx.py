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

Note on `CONCURRENTLY`: Postgres rejects it inside a transaction.
Alembic's default `env.py` wraps each migration in `begin_transaction()`,
so we set `transactional_ddl = False` at the module level. The downgrade
follows the same rule.

Owner action after merge:
    .venv/bin/python -m alembic upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "0011_vision_jobs_sha_idx"
down_revision = "0010_user_profile_onboarding_extensions"
branch_labels = None
depends_on = None

# `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. The
# project's `migrations/env.py` opens an explicit `begin_transaction()` for
# every migration. We break out of it by committing first, then run the
# DDL via the AUTOCOMMIT isolation level on the same connection. Same
# trick on downgrade.


def _run_concurrently(sql: str) -> None:
    from sqlalchemy import text

    bind = op.get_bind()
    # Commit the open Alembic transaction so we can switch isolation level.
    bind.execute(text("COMMIT"))
    with bind.execution_options(isolation_level="AUTOCOMMIT"):
        bind.execute(text(sql))


def upgrade() -> None:
    _run_concurrently(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_vision_jobs_sha_recent
        ON vision_jobs (image_sha256, created_at DESC)
        WHERE status = 'completed' AND detected_items IS NOT NULL
        """
    )


def downgrade() -> None:
    _run_concurrently(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_vision_jobs_sha_recent"
    )
