"""Dispatch push to all active tokens for a user. Marks failures as invalid."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.notifications.infrastructure.fcm_client import FcmClient
from app.notifications.infrastructure.web_push_client import WebPushClient

log = get_logger("notifications.send")


@dataclass(slots=True)
class SendNotification:
    session: AsyncSession
    web: WebPushClient
    fcm: FcmClient

    async def __call__(self, *, user_id: UUID, payload: dict) -> int:
        rows = (await self.session.execute(text("""
            SELECT id::text, platform, token, endpoint, p256dh, auth
              FROM push_tokens
             WHERE user_id = :uid AND invalid_at IS NULL
        """), {"uid": str(user_id)})).all()
        n_sent = 0
        for r in rows:
            ok = False
            if r[1] == "web" and r[3] and r[4] and r[5]:
                ok = await self.web.send(endpoint=r[3], p256dh=r[4], auth=r[5], payload=payload)
            elif r[1] in ("ios", "android"):
                ok = await self.fcm.send(token=r[2], payload=payload)
            if ok:
                n_sent += 1
                await self.session.execute(text("""
                    UPDATE push_tokens SET last_used_at = now() WHERE id = :id
                """), {"id": r[0]})
            else:
                await self.session.execute(text("""
                    UPDATE push_tokens SET invalid_at = now() WHERE id = :id
                """), {"id": r[0]})
        return n_sent
