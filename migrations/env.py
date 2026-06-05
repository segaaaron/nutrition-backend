"""Async Alembic env. Reads DATABASE_URL from app settings."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import String, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject DB URL from app settings (env-driven) so alembic.ini never holds creds.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Import metadata once domain models exist. For now Alembic operates in
# autogenerate-off mode (revisions hand-written).
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


_CREATE_ALEMBIC_VERSION_WIDE = (
    "CREATE TABLE IF NOT EXISTS alembic_version ("
    "version_num VARCHAR(255) NOT NULL, "
    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
    ");"
)
_ALTER_ALEMBIC_VERSION_WIDTH = (
    "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255);"
)


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Fresh DBs: create alembic_version with VARCHAR(255) from the start.
        version_table_pk_type=String(255),
    )
    with context.begin_transaction():
        context.run_migrations()


def _preflight_widen_alembic_version(connection: Connection) -> None:
    """Ensure alembic_version table exists with VARCHAR(255) version_num column.

    Two-step guard (both idempotent):
    1. CREATE TABLE IF NOT EXISTS with VARCHAR(255) -> fresh DBs (including those
       left tableless after a transactional rollback) get the correct type
       immediately, sidestepping alembic 1.14.1 ignoring `version_table_pk_type`.
    2. ALTER COLUMN to VARCHAR(255) -> pre-existing DBs created with the default
       VARCHAR(32) get widened.

    MUST commit before Alembic opens its own transaction and runs
    `UPDATE alembic_version SET version_num=...`; otherwise the change is not
    yet visible and long revision IDs are rejected.
    """
    connection.execute(text(_CREATE_ALEMBIC_VERSION_WIDE))
    connection.execute(text(_ALTER_ALEMBIC_VERSION_WIDTH))
    connection.commit()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Pre-flight in a dedicated, committed transaction. Idempotent: the DO block
    # is a no-op when the table does not yet exist (fresh DB) and a cheap
    # ALTER-to-same-type when already widened.
    async with connectable.connect() as preflight_conn:
        await preflight_conn.run_sync(_preflight_widen_alembic_version)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
