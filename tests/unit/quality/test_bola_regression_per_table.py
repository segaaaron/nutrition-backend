"""BOLA regression — `assert_owns` parametrised over every allowlisted
(table, id_col, user_col) triple.

For each owned resource declared in
``app.identity.presentation.dependencies._ASSERT_OWNS_ALLOWLIST`` we exercise
the three contractual branches:

  1. Owner match            → no exception.
  2. Owner mismatch (BOLA)  → Forbidden raised.
  3. Row not found          → NotFoundError raised.

Why this matters: the central allowlist is the single chokepoint protecting
plans / food_logs / fasting_sessions / progress_photos / vision_jobs /
coach_conversations / grocery_lists / grocery_items / notifications /
invoices / subscriptions / user_profiles. A regression in ``assert_owns``
on any of those would silently expose every endpoint that depends on it.
The pre-existing ``tests/unit/test_bola_audit.py`` only covers ``food_logs``
— this file expands coverage to the full allowlist.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.errors import Forbidden, NotFoundError
from app.identity.presentation.dependencies import (
    _ASSERT_OWNS_ALLOWLIST,
    assert_owns,
)

_ALLOWLIST = sorted(_ASSERT_OWNS_ALLOWLIST)


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.execute.return_value = MagicMock()
    return s


@pytest.mark.parametrize(("table", "id_col", "user_col"), _ALLOWLIST)
@pytest.mark.asyncio
async def test_owner_match_passes(
    session: AsyncMock, table: str, id_col: str, user_col: str
) -> None:
    uid = uuid4()
    session.execute.return_value.first.return_value = (str(uid),)
    await assert_owns(
        session,
        table=table,
        resource_id=uuid4(),
        user_id=uid,
        id_col=id_col,
        user_col=user_col,
    )


@pytest.mark.parametrize(("table", "id_col", "user_col"), _ALLOWLIST)
@pytest.mark.asyncio
async def test_bola_attempt_raises_forbidden(
    session: AsyncMock, table: str, id_col: str, user_col: str
) -> None:
    """User A asks for resource owned by User B → Forbidden."""
    user_a = uuid4()
    user_b = uuid4()
    assert user_a != user_b
    session.execute.return_value.first.return_value = (str(user_b),)
    with pytest.raises(Forbidden):
        await assert_owns(
            session,
            table=table,
            resource_id=uuid4(),
            user_id=user_a,
            id_col=id_col,
            user_col=user_col,
        )


@pytest.mark.parametrize(("table", "id_col", "user_col"), _ALLOWLIST)
@pytest.mark.asyncio
async def test_missing_row_raises_not_found(
    session: AsyncMock, table: str, id_col: str, user_col: str
) -> None:
    session.execute.return_value.first.return_value = None
    with pytest.raises(NotFoundError):
        await assert_owns(
            session,
            table=table,
            resource_id=uuid4(),
            user_id=uuid4(),
            id_col=id_col,
            user_col=user_col,
        )


@pytest.mark.asyncio
async def test_unlisted_table_rejected_by_allowlist_guard(session: AsyncMock) -> None:
    """SQL identifier injection defence — unknown table must abort."""
    with pytest.raises(ValueError, match="not in allowlist"):
        await assert_owns(
            session,
            table="users; DROP TABLE plans; --",
            resource_id=uuid4(),
            user_id=uuid4(),
        )
