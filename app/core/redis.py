"""Shared async Redis client.

Uses an explicit `ConnectionPool` so connection limits + keepalive are tunable
from settings. Default pool size (50) is sized for ~200 concurrent FastAPI
requests + Arq worker fan-out on the MVP VPS (KVM2). Adjust via
`REDIS_MAX_CONNECTIONS` env var.
"""

from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings

_pool: ConnectionPool | None = None
_client: Redis | None = None


def get_redis() -> Redis:
    # Module-level lazy singletons. Reset only in tests.
    global _pool, _client  # noqa: PLW0603
    if _client is None:
        s = get_settings()
        _pool = ConnectionPool.from_url(
            s.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=s.redis_max_connections,
            socket_keepalive=s.redis_socket_keepalive,
            health_check_interval=30,
        )
        _client = Redis(connection_pool=_pool)
    return _client


async def close_redis() -> None:
    # Module-level lazy singletons. Reset only in tests / shutdown.
    global _pool, _client  # noqa: PLW0603
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.disconnect(inuse_connections=True)
        _pool = None
