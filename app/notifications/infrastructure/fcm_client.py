"""FCM client placeholder — Phase 2.

The interface is stable so call sites can compile today; the actual HTTP
call lands when we ship mobile clients. For now `send` returns False and
logs at debug.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger

log = get_logger("notifications.fcm")


@dataclass(slots=True)
class FcmClient:
    async def send(self, *, token: str, payload: dict) -> bool:
        log.debug("fcm.noop", token_tail=token[-8:])
        return False
