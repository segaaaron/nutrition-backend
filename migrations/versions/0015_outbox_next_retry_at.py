"""0015 — Outbox replay backoff column.

Adds ``next_retry_at TIMESTAMPTZ NULL`` to ``outbox`` so the drainer
(``worker/outbox_drainer.py``) can implement exponential backoff
between replay attempts without sleeping in-task.

Drainer semantics post-migration:
- ``SELECT ... WHERE dispatched_at IS NULL
   AND (next_retry_at IS NULL OR next_retry_at <= now())``
- On replay failure: ``UPDATE outbox SET attempts = attempts + 1,
   next_retry_at = now() + interval based on attempts (capped 30min),
   last_error = '<exc>'``.

Reversibility: column drop is safe — drainer falls back to "process all
undispatched" semantics on downgrade.

Schema migration is additive + nullable; existing rows continue to work.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_outbox_next_retry_at"
down_revision = "0014_pending_registration_otp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column(
            "next_retry_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    # Partial index keeps the drainer's hot path SELECT cheap: only
    # rows that are still pending. The drainer's WHERE clause carries
    # the ``next_retry_at`` predicate; the index supports ordering by
    # ``next_retry_at NULLS FIRST, created_at``. Cannot include
    # ``next_retry_at <= now()`` in the predicate because ``now()`` is
    # non-immutable (Postgres rejects it in partial-index predicates).
    op.execute(
        "CREATE INDEX outbox_pending_idx "
        "ON outbox (next_retry_at NULLS FIRST, created_at) "
        "WHERE dispatched_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS outbox_pending_idx")
    op.drop_column("outbox", "next_retry_at")
