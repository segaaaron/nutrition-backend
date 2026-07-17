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

    # Must match the engine the app actually runs on (docker/db.Dockerfile builds
    # FROM timescale/timescaledb-ha:pg16; prod runs the pg17 variant). The old
    # pgvector/pgvector:pg16 image carries `vector` but NOT `timescaledb`, so
    # migration 0001_init died on `CREATE EXTENSION timescaledb` and the whole
    # integration suite errored at setup. The timescaledb-ha image bundles both.
    container = PostgresContainer(
        image="timescale/timescaledb-ha:pg16",
        username="nova",
        password="nova",  # noqa: S106 — ephemeral testcontainer, torn down post-module
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
    """Run Alembic upgrade head against the testcontainer DB.

    This used to stop at 0010 and hand-create 0011's partial index as plain DDL,
    on the belief that Alembic could not run `CREATE INDEX CONCURRENTLY`. That is
    no longer true — 0011 (and 0012/0016/0027) wrap it in Alembic's official
    `op.get_context().autocommit_block()`. Meanwhile the schema moved on to 0034,
    so freezing tests at 0010 meant they ran against a schema missing columns the
    models require (`phash_64`, added in 0013) and every test errored out. Migrate
    to head: tests must see the schema production actually has.
    """
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", pg_url)

    # `migrations/env.py` OVERWRITES sqlalchemy.url with `get_settings().database_url`
    # ("Reads DATABASE_URL from app settings"), so the cfg value above is ignored and
    # Alembic would target whatever DATABASE_URL happens to be set — by default the
    # `test:test@localhost:5432` placeholder in tests/conftest.py, i.e. some unrelated
    # Postgres on the dev machine (or nothing). Point the env var at THIS container and
    # drop the lru_cache so env.py resolves the testcontainer.
    prev_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = pg_url
    get_settings.cache_clear()
    try:
        # 0030, not "head": 0031 is a DATA migration that DELETEs/INSERTs
        # recipe_components for the authored meals_v4 recipe ids. Those rows were
        # seeded into PROD, not created by a migration, so on an empty DB the
        # INSERT trips recipe_components_recipe_id_fkey and the whole suite dies.
        # 0030 is also exactly the revision PROD runs today, and it carries every
        # column the vision models need (prompt_sha256 from 0002, phash_64 from
        # 0013). Move this to "head" once 0031 is made safe on a fresh database.
        command.upgrade(cfg, "0030_recipe_component_name_en")
    finally:
        if prev_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_url
        get_settings.cache_clear()

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
