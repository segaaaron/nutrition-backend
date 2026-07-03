"""SSE ticket — short-lived (30s) auth token for browser EventSource.

Per spec §12 + finding #19: browsers can't set Authorization headers on
EventSource so we mint a per-conv ticket on POST /coach/sse-ticket then
the SSE endpoint accepts `?ticket=…`. Ticket is sha256-hashed in DB so a
leaked log line can't be reused.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthTicketInvalid

TICKET_TTL_S = 30


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def mint(session: AsyncSession, *, user_id: UUID, conv_id: UUID) -> str:
    # Lazy cleanup: purge old expired tickets on each mint. Table is tiny (30s TTL).
    await session.execute(text("DELETE FROM coach_sse_tickets WHERE expires_at < now()"))
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=TICKET_TTL_S)
    await session.execute(
        text(
            """
        INSERT INTO coach_sse_tickets (token_hash, user_id, conv_id, expires_at)
        VALUES (:h, :uid, :cid, :exp)
    """
        ),
        {"h": _hash(token), "uid": str(user_id), "cid": str(conv_id), "exp": expires},
    )
    return token


async def consume(session: AsyncSession, *, token: str) -> tuple[UUID, UUID]:
    row = (
        await session.execute(
            text(
                """
        DELETE FROM coach_sse_tickets
         WHERE token_hash = :h AND expires_at > now()
         RETURNING user_id::text, conv_id::text
    """
            ),
            {"h": _hash(token)},
        )
    ).first()
    if not row:
        raise AuthTicketInvalid("ticket_invalid_or_expired")
    return (UUID(row[0]), UUID(row[1]))


async def cleanup_expired(session: AsyncSession) -> int:
    res = await session.execute(
        text(
            """
        DELETE FROM coach_sse_tickets WHERE expires_at < now()
    """
        )
    )
    return res.rowcount or 0
