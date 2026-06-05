"""0012 — re-assert partial unique index on nutritional_goals (active row).

Sprint 3 D5 — Recalibration race condition fix.

Context
-------
The `RecalibrateGoals` use case in `app/nutrition/application/use_cases.py`
performs read-then-write on the user's active nutritional goal row:

    1. SELECT current active goal (where valid_to IS NULL)
    2. UPDATE current.valid_to = now()
    3. INSERT new active row (valid_to = NULL)

Under concurrent execution (e.g. a duplicate WeightLogged event delivered
twice by the bus, or a manual recalibration overlapping with the
auto-trigger) two parallel transactions can both reach step 3 and insert
two active rows for the same user, corrupting the state machine.

Defence in depth
----------------
Layer 1 (already shipped in migration 0001):

    CREATE UNIQUE INDEX one_current_goals
    ON nutritional_goals (user_id) WHERE valid_to IS NULL

This Postgres partial unique constraint is the authoritative invariant.
A second concurrent INSERT raises `psycopg.errors.UniqueViolation` →
SQLAlchemy `IntegrityError`, which the use case now catches and reports
as `RecalibrationSkipped("concurrent_recalibration")`.

Layer 2 (this migration): we **re-assert** the index `IF NOT EXISTS`
so the contract is documented at the canonical sprint-3 revision and
survives any historical drift (e.g. a hot-fix DROP INDEX that was never
recreated). Idempotent and safe on fresh databases.

Layer 3 (application code): `pg_advisory_xact_lock(hash(user_id))` is
acquired at the start of the recalibration transaction. This serialises
concurrent recalibrations per-user without blocking other users and
turns the race into a clean queue. The unique constraint remains the
last-line defence.

Reversibility
-------------
Downgrade drops the index. Note this leaves the database in a state
where the application invariant is no longer enforced at the storage
layer — only suitable for local rollback, never production.

CONCURRENTLY
------------
Index created CONCURRENTLY to avoid locking the table during deploy.
Same transaction-management trick as migration 0011.
"""
from __future__ import annotations

from alembic import op

revision = "0012_nutritional_goals_active_unique"
down_revision = "0011_vision_jobs_sha_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent re-assertion. The canonical index was created in 0001 as
    # `one_current_goals`; we keep the same name so this is a no-op on
    # any database that has been through migration 0001 cleanly.
    #
    # `op.get_context().autocommit_block()` is the SQLAlchemy 2.0 + Alembic
    # safe way to run `CREATE INDEX CONCURRENTLY` — manually toggling
    # `isolation_level="AUTOCOMMIT"` on a bound connection raises
    # `InvalidRequestError` because the tx is already autobegun.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS one_current_goals
            ON nutritional_goals (user_id)
            WHERE valid_to IS NULL
            """
        )


def downgrade() -> None:
    # Intentionally drops the invariant. Only safe in local rollback —
    # in production, prefer point-in-time recovery over downgrade.
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS one_current_goals"
        )
