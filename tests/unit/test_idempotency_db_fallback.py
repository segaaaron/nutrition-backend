import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.identity.presentation.dependencies import (
    db_lookup_idempotent,
    remember_idempotent,
)


@pytest.fixture
def fake_session():
    s = AsyncMock()
    # execute() is awaitable, but its result's .first() is synchronous
    # (matching real SQLAlchemy CursorResult behaviour).
    s.execute.return_value = MagicMock()
    return s


async def test_db_lookup_returns_cached_body(fake_session):
    fake_session.execute.return_value.first.return_value = ({"ok": True, "n": 1},)
    body = await db_lookup_idempotent(fake_session, "idem:abc")
    assert body == {"ok": True, "n": 1}


async def test_db_lookup_returns_none_when_missing(fake_session):
    fake_session.execute.return_value.first.return_value = None
    body = await db_lookup_idempotent(fake_session, "idem:miss")
    assert body is None


async def test_remember_writes_to_redis_and_db(fake_redis, fake_session):
    await remember_idempotent("idem:xyz", {"n": 2}, session=fake_session, redis=fake_redis)
    raw = await fake_redis.get("idem:xyz")
    assert json.loads(raw) == {"n": 2}
    fake_session.execute.assert_awaited()
