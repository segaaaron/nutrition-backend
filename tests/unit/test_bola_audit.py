"""OWASP API1 (BOLA) — assert_owns helper rejects non-owners.

Tests:
  1. No exception when user_id matches the row's owner.
  2. Forbidden raised when user_id does NOT match.
  3. NotFoundError raised when the row doesn't exist.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.errors import Forbidden, NotFoundError
from app.identity.presentation.dependencies import assert_owns


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.execute.return_value = MagicMock()
    return s


@pytest.mark.asyncio
async def test_owns_when_user_id_matches(session: AsyncMock) -> None:
    """No exception when the row's user_id equals current_user."""
    uid = uuid4()
    rid = uuid4()
    session.execute.return_value.first.return_value = (str(uid),)
    # Should complete without raising.
    await assert_owns(session, table="food_logs", resource_id=rid, user_id=uid)


@pytest.mark.asyncio
async def test_forbidden_when_user_mismatch(session: AsyncMock) -> None:
    """Forbidden raised when jwt.sub != resource.user_id."""
    other_user = uuid4()
    requester = uuid4()
    assert other_user != requester  # sanity
    session.execute.return_value.first.return_value = (str(other_user),)
    with pytest.raises(Forbidden):
        await assert_owns(
            session, table="food_logs", resource_id=uuid4(), user_id=requester,
        )


@pytest.mark.asyncio
async def test_not_found_when_row_missing(session: AsyncMock) -> None:
    """NotFoundError raised when the row does not exist."""
    session.execute.return_value.first.return_value = None
    with pytest.raises(NotFoundError):
        await assert_owns(
            session, table="food_logs", resource_id=uuid4(), user_id=uuid4(),
        )
