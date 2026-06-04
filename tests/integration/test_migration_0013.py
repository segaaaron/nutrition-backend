"""Integration test — migration 0013 leaderboard anti-cheat schema.

Boots a real Postgres via testcontainers, runs the full Alembic chain
up to 0013, asserts the schema is present, then downgrades one step
and asserts the schema is gone again.

Skipped automatically when Docker is unavailable.
"""

from __future__ import annotations

import os
import uuid

import pytest

DOCKER_AVAILABLE: bool
try:
    import docker as _docker

    _docker_client = _docker.from_env()  # type: ignore[attr-defined]
    _docker_client.ping()
    DOCKER_AVAILABLE = True
except Exception:  # noqa: BLE001
    DOCKER_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker daemon not reachable — required for testcontainers",
)


def _alembic_cfg(sync_url: str):
    from alembic.config import Config

    cfg = Config(
        os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    )
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


@pytest.fixture(scope="module")
def pg_container():
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="nova",
        password="nova",  # noqa: S106 — testcontainer-only credential
        dbname="nova_test_0013",
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
def sync_url(pg_container):
    raw = pg_container.get_connection_url()
    return raw.replace("postgresql+psycopg2://", "postgresql://")


def test_migration_0013_upgrade_creates_schema(sync_url):
    import sqlalchemy as sa
    from alembic import command

    cfg = _alembic_cfg(sync_url)
    # 0011 CONCURRENTLY index is a no-op on an empty test DB; we skip
    # past it by upgrading to 0010 then plain DDL the index, mirroring
    # the vision conftest trick.
    command.upgrade(cfg, "0010_user_profile_onboarding_extensions")
    eng = sa.create_engine(sync_url)
    with eng.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_vision_jobs_sha_recent
                ON vision_jobs (image_sha256, created_at DESC)
                WHERE status = 'completed' AND detected_items IS NOT NULL
                """
            )
        )
    eng.dispose()
    command.upgrade(cfg, "0013_leaderboard_anti_cheat")

    eng = sa.create_engine(sync_url)
    try:
        with eng.connect() as conn:
            tables = set(
                r[0]
                for r in conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            assert "profile_region_change_audit" in tables
            assert "gamification_shadow_ban" in tables
            assert "leaderboard_audit" in tables

            # vision_jobs.phash_64 column exists.
            cols = set(
                r[0]
                for r in conn.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'vision_jobs'"
                    )
                )
            )
            assert "phash_64" in cols

            # Feature flag seeded OFF.
            flag = conn.execute(
                sa.text(
                    "SELECT enabled FROM feature_flags "
                    "WHERE key = 'leaderboard_l1_caps_enabled'"
                )
            ).scalar()
            assert flag is False

            # UNIQUE constraint on leaderboard_audit.idempotency_key.
            uid = uuid.uuid4()
            # Need a real users row for the FK.
            with conn.begin():
                conn.execute(
                    sa.text(
                        "INSERT INTO users (id, email, password_hash, created_at) "
                        "VALUES (:id, :em, 'x', now())"
                    ),
                    {"id": str(uid), "em": f"{uid}@t.local"},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO leaderboard_audit "
                        "(user_id, action, xp_delta, source, idempotency_key) "
                        "VALUES (:uid, 'food_logged', 10, 'text', 'key-1')"
                    ),
                    {"uid": str(uid)},
                )
            with pytest.raises(Exception):  # noqa: B017, PT011 — driver-specific UNIQUE-violation type
                with conn.begin():
                    conn.execute(
                        sa.text(
                            "INSERT INTO leaderboard_audit "
                            "(user_id, action, xp_delta, source, idempotency_key) "
                            "VALUES (:uid, 'food_logged', 10, 'text', 'key-1')"
                        ),
                        {"uid": str(uid)},
                    )
    finally:
        eng.dispose()


def test_migration_0013_downgrade_removes_schema(sync_url):
    import sqlalchemy as sa
    from alembic import command

    cfg = _alembic_cfg(sync_url)
    command.downgrade(cfg, "0012_nutritional_goals_active_unique")

    eng = sa.create_engine(sync_url)
    try:
        with eng.connect() as conn:
            tables = set(
                r[0]
                for r in conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            assert "profile_region_change_audit" not in tables
            assert "gamification_shadow_ban" not in tables
            assert "leaderboard_audit" not in tables
            cols = set(
                r[0]
                for r in conn.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'vision_jobs'"
                    )
                )
            )
            assert "phash_64" not in cols
    finally:
        eng.dispose()
