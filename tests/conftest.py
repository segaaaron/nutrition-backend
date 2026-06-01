"""Shared pytest fixtures. Integration tests use testcontainers; unit tests
do not depend on this file's infrastructure fixtures.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def fake_redis():
    import fakeredis.aioredis
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()
