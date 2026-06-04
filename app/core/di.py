"""Dependency-injection wiring. Per-context providers register here so
presentation routers can `Depends(...)` without importing infrastructure
directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session
