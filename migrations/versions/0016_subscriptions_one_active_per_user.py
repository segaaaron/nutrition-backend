"""0016 — Subscriptions one-active-per-user invariant (DB level).

Patrón #5 — Invariantes post-mutación.

Context
-------
``HandleWebhook`` in ``app/billing/use_cases.py`` previously called
``Subscription(id=uuid4(), ...)`` on every ``subscription.created`` /
``checkout.session.completed`` event. The ``upsert_subscription`` SQL uses
``ON CONFLICT (id) DO UPDATE`` — but with a fresh ``uuid4()`` per event
the conflict path is *never* taken, so two concurrent (or replayed)
webhooks for the same user could insert two rows with
``status='active'``. ``get_subscription`` then returns whichever row sorts
``created_at DESC`` first, hiding the duplicate from the application but
corrupting the billing audit trail and entitlement queries.

Defence in depth
----------------
Layer 1 (this migration) — partial UNIQUE index on ``user_id`` filtered to
live statuses (``trialing``, ``active``, ``past_due``). A duplicate
``INSERT`` raises ``psycopg.errors.UniqueViolation`` → SQLAlchemy
``IntegrityError`` which the application catches as a no-op (the existing
row is the source of truth; the second webhook is treated as a replay).

Layer 2 (application code) — ``HandleWebhook`` now reuses any existing
subscription row id for the user instead of minting a new uuid, so the
``ON CONFLICT (id) DO UPDATE`` path engages naturally and the UNIQUE
index above becomes the last-line defence.

Reversibility
-------------
Downgrade drops the index. Index creation uses ``CONCURRENTLY`` to avoid
locking the ``subscriptions`` table during deploy (CLAUDE.md zero-downtime
migration policy).
"""
from __future__ import annotations

from alembic import op


revision = "0016_subscriptions_one_active_per_user"
down_revision = "0015_outbox_next_retry_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction block.
    # Same SQLAlchemy 2.0 + Alembic pattern used by migration 0012.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                uq_subscriptions_one_live_per_user
              ON subscriptions (user_id)
             WHERE status IN ('trialing', 'active', 'past_due')
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS uq_subscriptions_one_live_per_user"
        )
