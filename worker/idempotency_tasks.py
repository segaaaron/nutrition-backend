"""Arq cron task: purge expired rows from the idempotency_keys table."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import get_logger

logger = get_logger(__name__)


async def cleanup_idempotency_keys_cron(ctx: dict[str, Any]) -> int:  # noqa: ARG001
    """Delete expired idempotency_keys rows. Scheduled nightly at 03:30 UTC."""
    async with session_scope() as session:
        res = await session.execute(text(
            "DELETE FROM idempotency_keys WHERE expires_at < now()"
        ))
        await session.commit()
        deleted: int = res.rowcount
    logger.info("idempotency_keys.cleanup", deleted=deleted)
    return deleted
