"""Unit — Redis client uses an explicit ConnectionPool with tuned size.

Default max_connections is 50 (sized for ~200 concurrent FastAPI requests +
Arq worker fan-out on the MVP VPS). Override via REDIS_MAX_CONNECTIONS.
"""

from __future__ import annotations

import pytest

from app.core import redis as redis_mod
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    redis_mod._client = None
    redis_mod._pool = None
    yield
    redis_mod._client = None
    redis_mod._pool = None


def test_get_redis_creates_pool_with_configured_max_connections() -> None:
    client = redis_mod.get_redis()
    pool = redis_mod._pool
    assert pool is not None
    settings = get_settings()
    assert pool.max_connections == settings.redis_max_connections
    # client must share the pool
    assert client.connection_pool is pool


def test_get_redis_returns_singleton() -> None:
    a = redis_mod.get_redis()
    b = redis_mod.get_redis()
    assert a is b


def test_settings_default_max_connections_is_50() -> None:
    settings = get_settings()
    assert settings.redis_max_connections == 50
    assert settings.redis_socket_keepalive is True
