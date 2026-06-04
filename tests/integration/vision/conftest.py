"""Integration fixtures for the vision context.

Requires Docker (testcontainers spins up a real Postgres + pgvector).
Run with: `pytest tests/integration/vision/ -m integration`
Skip locally with: `pytest -m 'not integration'`.

Strategy:
- Module-scoped Postgres container (boot ~3-5s).
- Apply Alembic migrations once at module setup.
- Per-test isolation via SAVEPOINT / TRUNCATE.
- Redis is faked in-process (`fakeredis.aioredis`) — no second container.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

DOCKER_AVAILABLE: bool
try:
    import docker as _docker

    _docker_client = _docker.from_env()  # type: ignore[attr-defined]
    _docker_client.ping()
    DOCKER_AVAILABLE = True
except Exception:  # noqa: BLE001 - intentionally permissive: any failure means skip
    DOCKER_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker daemon not reachable — required for testcontainers",
)


@pytest.fixture(scope="module")
def pg_container() -> Iterator[Any]:
    """Boot a Postgres 16 + pgvector container for the module."""
    if not DOCKER_AVAILABLE:
        pytest.skip("docker not available")

    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    # pgvector image carries the `vector` extension preinstalled.
    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="nova",
        password="nova",
        dbname="nova_test",
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def pg_url(pg_container: Any) -> str:
    """asyncpg-style URL for SQLAlchemy."""
    raw = pg_container.get_connection_url()
    # testcontainers returns psycopg2 driver by default — swap to asyncpg.
    out: str = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    return out


@pytest.fixture(scope="module")
def _apply_migrations(pg_url: str) -> str:
    """Run Alembic upgrade head against the testcontainer DB."""
    # Alembic does not handle the CREATE INDEX CONCURRENTLY trick on a brand-new
    # DB cleanly inside testcontainers (no traffic to serialise). For test
    # purposes we apply 0001-0010 via Alembic and add 0011's index by hand as
    # plain (non-concurrent) DDL.
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "..", "alembic.ini"))
    sync_url = pg_url.replace("+asyncpg", "")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    # Stop one before 0011 — the partial index is created manually below.
    command.upgrade(cfg, "0010_user_profile_onboarding_extensions")

    # Add the migration 0011 partial index plain (no CONCURRENTLY) for tests.
    import sqlalchemy as sa

    sync_engine = sa.create_engine(sync_url)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                """
            CREATE INDEX IF NOT EXISTS ix_vision_jobs_sha_recent
            ON vision_jobs (image_sha256, created_at DESC)
            WHERE status = 'completed' AND detected_items IS NOT NULL
            """
            )
        )
    sync_engine.dispose()
    return pg_url


@pytest_asyncio.fixture
async def async_engine(_apply_migrations: str) -> AsyncIterator[Any]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_apply_migrations, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine: Any) -> AsyncIterator[Any]:
    """Per-test session with TRUNCATE cleanup of vision tables."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(async_engine, expire_on_commit=False)
    async with Session() as s:
        yield s
        await s.rollback()

    # Wipe vision-related rows between tests for isolation. Keep schema.
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE food_logs, vision_jobs, vision_user_corrections "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def fake_user_id(async_engine: Any) -> AsyncIterator[Any]:
    """Insert a real users row (FK target for vision_jobs.user_id)."""
    import uuid

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = uuid.uuid4()
    Session = async_sessionmaker(async_engine, expire_on_commit=False)
    async with Session() as s:
        await s.execute(
            text(
                "INSERT INTO users (id, email, password_hash, created_at) "
                "VALUES (:id, :em, :ph, now())"
            ),
            {"id": str(uid), "em": f"{uid}@test.local", "ph": "x"},
        )
        await s.commit()
    yield uid


@pytest_asyncio.fixture
async def fake_redis_client() -> AsyncIterator[Any]:
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()
