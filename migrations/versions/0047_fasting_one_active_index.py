"""0047 — Unique partial index: one active fasting session per user.

Enforces the invariant that a user can have at most one open fasting session
(``end_ts IS NULL``) at any time. The application-level read-then-write guard in
``StartFasting`` cannot enforce it: two concurrent requests both read "no active
session" before either inserts, and both insert. That is a double tap or a
network retry, not an exotic race.

Reported by iOS on 2026-08-22 (point 3 of ``REVIEW-ENTREGA-2026-08-22.md``): the
router carried a comment asserting this invariant held "inside StartFasting"
while the schema had nothing to hold it.

The pre-flight below is required, not defensive: ``CREATE UNIQUE INDEX`` fails
outright if duplicates already exist, and any account that hit the race is
carrying a pair right now.

Not ``CONCURRENTLY``: that cannot run inside a transaction, and Alembic wraps
each migration in one. ``fasting_sessions`` is small and the write lock is brief.
If this table grows past the point where a brief exclusive lock is acceptable,
split the index creation into its own autocommit migration.

Revision: 0047_fasting_one_active_index
"""

from alembic import op

revision = "0047_fasting_one_active_index"
down_revision = "0046_weight_logs_waist_cm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Close every duplicate open session, keeping the most recently started one
    # per user — the same row ``active_for`` already returns since 0185256
    # (``ORDER BY start_ts DESC``), so this preserves what the app is showing.
    #
    # The losers are closed at their own start: zero duration, not achieved. They
    # are phantom rows the user never saw a countdown for, and inventing a
    # duration for them would feed the streak a fast nobody did.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id ORDER BY start_ts DESC, id
                   ) AS rn
              FROM fasting_sessions
             WHERE end_ts IS NULL
        )
        UPDATE fasting_sessions AS fs
           SET end_ts     = fs.start_ts,
               duration_s = 0,
               achieved   = false
          FROM ranked AS r
         WHERE fs.id = r.id
           AND r.rn > 1
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_fasting_one_active
            ON fasting_sessions(user_id)
         WHERE end_ts IS NULL
        """
    )


def downgrade() -> None:
    # The closed duplicates are not restored: they carried no information beyond
    # their existence, and reopening them would recreate the bug this migration
    # exists to prevent.
    op.execute("DROP INDEX IF EXISTS ix_fasting_one_active")
