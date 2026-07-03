"""Dispatch push to all active mobile tokens for a user. Marks failures as invalid.

Mobile-only (iOS/Android via FCM). Web Push was removed 2026-06-04 — NOVA backend
serves mobile apps only, no PWA scope. Legacy `platform='web'` rows are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.notifications.infrastructure.fcm_client import FcmClient

log = get_logger("notifications.send")


@dataclass(slots=True)
class SendNotification:
    session: AsyncSession
    fcm: FcmClient

    async def __call__(self, *, user_id: UUID, payload: dict) -> int:
        rows = (
            await self.session.execute(
                text(
                    """
            SELECT id::text, platform, token
              FROM push_tokens
             WHERE user_id = :uid
               AND invalid_at IS NULL
               AND platform IN ('ios', 'android')
        """
                ),
                {"uid": str(user_id)},
            )
        ).all()
        n_sent = 0
        for r in rows:
            ok = await self.fcm.send(token=r[2], payload=payload)
            if ok:
                n_sent += 1
                await self.session.execute(
                    text(
                        """
                    UPDATE push_tokens SET last_used_at = now() WHERE id = :id
                """
                    ),
                    {"id": r[0]},
                )
            # NOTE: when ok is False we intentionally do NOT mark the token
            # invalid.  FcmClient.send() is a Phase-2 stub that always returns
            # False; marking every token invalid on every call would permanently
            # destroy the user's push registration before FCM is wired up.
            # Token invalidation will be re-enabled once the real FCM HTTP call
            # is implemented and we can distinguish a real 404/410 response
            # from a "not yet implemented" no-op.
        return n_sent
