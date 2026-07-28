"""Async SQLAlchemy engine + session factory. Pool sized to Postgres
max_connections=75 on the Hostinger VPS (spec §23.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine  # noqa: PLW0603 — lazy module-level singleton, intentional
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=s.db_pool_recycle_seconds,
            future=True,
        )

        # Register the pgvector asyncpg codec on every new connection.
        # Without this, `SELECT embedding FROM recipes` via raw SQL returns
        # the vector as the string "[0.1,...]" instead of a float sequence,
        # and Layer3 ranking's `list(emb)` yields characters → crashes plan
        # generation once recipe embeddings are non-NULL. The vision/coach
        # paths are unaffected (they compute cosine in SQL via `<=>` and
        # never read a raw vector column into Python).
        @event.listens_for(_engine.sync_engine, "connect")
        def _register_pgvector(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            from pgvector.asyncpg import register_vector

            dbapi_connection.run_async(register_vector)

    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker  # noqa: PLW0603 — lazy module-level singleton, intentional
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session with post-commit event dispatch.

    Opens a deferred-publish scope (ADR-0030) so any ``bus.publish``
    called inside the ``with`` block queues into a request-local list.
    On clean exit we commit the DB transaction first and only then
    dispatch the queued events — guaranteeing that handlers which open
    fresh sessions see committed data. On exception we discard the
    queue without dispatching.
    """
    from app.core.event_bus import (
        begin_request_scope,
        discard_request_scope,
        flush_request_scope,
        get_event_bus,
        is_request_scope_active,
    )

    sm = get_sessionmaker()
    # Nest cleanly: if a request-scope is already active (e.g. FastAPI
    # dep opened one), defer to it — do NOT open a second scope, which
    # would split the queue and dispatch events twice.
    nested = is_request_scope_active()
    token = None if nested else begin_request_scope()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:  # noqa: BLE001 — OK5: session rollback wrapper; re-raises after rollback
            await session.rollback()
            if token is not None:
                discard_request_scope(token)
            raise
        else:
            if token is not None:
                await flush_request_scope(get_event_bus(), token)


async def dispose_engine() -> None:
    global _engine, _sessionmaker  # noqa: PLW0603 — shutdown teardown of lazy singleton
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
