"""Migration 0011 upgrade -> downgrade -> upgrade cycle.

Why this test exists
--------------------
Migration 0011 adds a partial index on ``vision_jobs(image_sha256, created_at DESC)``
created with ``CONCURRENTLY``. The migration uses a hand-rolled escape from
Alembic's transaction wrapping (commits, switches isolation to AUTOCOMMIT, runs
the DDL). That escape is exactly the kind of code that breaks silently on
``downgrade``.

What we verify
--------------
1. ``upgrade()`` produces an index with the documented name + predicate.
2. ``downgrade()`` removes it cleanly (no orphan, no error).
3. Re-running ``upgrade()`` is idempotent (``IF NOT EXISTS`` guard works).
4. Re-running ``downgrade()`` is idempotent (``IF EXISTS`` guard works).
5. The migration's helper ``_run_concurrently`` commits the outer txn before
   switching isolation level — without that commit, Postgres rejects
   ``CREATE INDEX CONCURRENTLY``.

Gating
------
- Pure SQL-string assertions (no DB) run unconditionally in unit mode.
- The live cycle test against a real Postgres container is marked
  ``integration`` and only runs with ``--run-integration``.
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest

MIGRATION_MODULE = "migrations.versions.0011_vision_jobs_sha_idx"


def _load_migration() -> Any:
    """Import the migration module by file path (the dotted name starts with
    a digit so plain ``importlib`` rejects it)."""
    import importlib.util

    here = os.path.dirname(__file__)
    path = os.path.normpath(
        os.path.join(here, "..", "..", "migrations", "versions", "0011_vision_jobs_sha_idx.py")
    )
    spec = importlib.util.spec_from_file_location("_mig_0011", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Unit: shape checks against the migration source (no DB required).
# ---------------------------------------------------------------------------


def test_migration_declares_correct_revision_chain() -> None:
    mod = _load_migration()

    assert mod.revision == "0011_vision_jobs_sha_idx"
    assert mod.down_revision == "0010_user_profile_onboarding_extensions"


def test_upgrade_creates_named_partial_index_with_if_not_exists() -> None:
    """Idempotent re-upgrade depends on IF NOT EXISTS."""
    import inspect

    mod = _load_migration()
    src = inspect.getsource(mod.upgrade)

    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in src
    assert "ix_vision_jobs_sha_recent" in src
    assert "vision_jobs" in src
    assert "image_sha256" in src
    assert "created_at DESC" in src
    # The partial predicate is what makes the cache hit cheap.
    assert "status = 'completed'" in src
    assert "detected_items IS NOT NULL" in src


def test_downgrade_drops_named_index_with_if_exists() -> None:
    """Idempotent re-downgrade depends on IF EXISTS."""
    import inspect

    mod = _load_migration()
    src = inspect.getsource(mod.downgrade)

    assert "DROP INDEX CONCURRENTLY IF EXISTS" in src
    assert "ix_vision_jobs_sha_recent" in src


def test_run_concurrently_uses_autocommit_block() -> None:
    """CONCURRENTLY is rejected inside an open transaction.

    The migration uses Alembic's ``op.get_context().autocommit_block()``
    context manager (the official Alembic >=1.13 pattern) which commits the
    outer migration transaction and switches to AUTOCOMMIT automatically.
    This is safer than the old manual ``text("COMMIT") + AUTOCOMMIT`` pattern
    because Alembic handles isolation-level restoration after the block.
    """
    import inspect

    mod = _load_migration()
    upgrade_src = inspect.getsource(mod.upgrade)
    downgrade_src = inspect.getsource(mod.downgrade)

    assert "autocommit_block" in upgrade_src, (
        "upgrade() must use op.get_context().autocommit_block() to run "
        "CREATE INDEX CONCURRENTLY outside a transaction"
    )
    assert "autocommit_block" in downgrade_src, (
        "downgrade() must use op.get_context().autocommit_block() to run "
        "DROP INDEX CONCURRENTLY outside a transaction"
    )


def test_upgrade_and_downgrade_share_index_name() -> None:
    """If the names diverge, downgrade leaves the index in place forever."""
    import inspect

    mod = _load_migration()
    name_re = re.compile(r"ix_vision_jobs_sha_recent")

    assert name_re.search(inspect.getsource(mod.upgrade))
    assert name_re.search(inspect.getsource(mod.downgrade))


# ---------------------------------------------------------------------------
# Integration: live cycle against a real Postgres container.
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
def test_0011_upgrade_downgrade_upgrade_cycle_against_postgres() -> None:
    """Boot Postgres, apply 0010, run 0011 upgrade -> downgrade -> upgrade.

    Asserts:
    - index exists after first upgrade
    - index gone after downgrade
    - re-running upgrade is idempotent (no error, index re-created)
    - re-running downgrade is idempotent (no error)
    """
    try:
        import docker as _docker

        _docker.from_env().ping()  # type: ignore[attr-defined]
    except Exception:
        pytest.skip("Docker daemon not reachable")

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    with PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="nova",
        password="nova",  # noqa: S106 — ephemeral testcontainer, torn down per test
        dbname="nova_test",
    ) as pg:
        sync_url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

        cfg = Config(
            os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
        )
        cfg.set_main_option("sqlalchemy.url", sync_url)

        # Bring schema up to the migration before 0011.
        command.upgrade(cfg, "0010_user_profile_onboarding_extensions")

        engine = sa.create_engine(sync_url)
        index_q = sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = 'ix_vision_jobs_sha_recent'"
        )

        # 1. upgrade -> index exists
        command.upgrade(cfg, "0011_vision_jobs_sha_idx")
        with engine.connect() as conn:
            assert conn.execute(index_q).scalar() == 1

        # 2. downgrade -> index gone
        command.downgrade(cfg, "0010_user_profile_onboarding_extensions")
        with engine.connect() as conn:
            assert conn.execute(index_q).scalar() is None

        # 3. re-upgrade -> idempotent, index back
        command.upgrade(cfg, "0011_vision_jobs_sha_idx")
        with engine.connect() as conn:
            assert conn.execute(index_q).scalar() == 1

        # 4. second upgrade in a row -> IF NOT EXISTS makes this a no-op
        #    (alembic refuses to re-apply same head, so call helper directly).
        mod = _load_migration()
        with engine.begin() as conn:
            # Mimic Alembic context for the helper.
            from alembic.operations import Operations
            from alembic.runtime.migration import MigrationContext

            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            # Patch the global op reference the migration imported.
            mod.op = op
            mod.upgrade()  # must not raise
            mod.downgrade()  # must not raise (IF EXISTS guard)
            mod.downgrade()  # second downgrade still must not raise

        engine.dispose()
