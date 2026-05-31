"""Web Push (VAPID) sender — best-effort, marks invalid tokens on 410/404.

Requires pywebpush in pyproject. VAPID keys loaded from env
(NOVA_VAPID_PRIVATE_KEY + NOVA_VAPID_PUBLIC_KEY + NOVA_VAPID_CONTACT_EMAIL).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.core.logging import get_logger

log = get_logger("notifications.webpush")


@dataclass(slots=True)
class WebPushClient:
    async def send(
        self, *, endpoint: str, p256dh: str, auth: str, payload: dict,
    ) -> bool:
        try:
            from pywebpush import WebPushException, webpush  # type: ignore
        except Exception as exc:  # noqa: BLE001
            log.warning("webpush.lib_missing", err=str(exc))
            return False
        vapid_private = os.getenv("NOVA_VAPID_PRIVATE_KEY", "")
        vapid_email = os.getenv("NOVA_VAPID_CONTACT_EMAIL", "ops@nova-nutrition.com")
        if not vapid_private:
            log.warning("webpush.no_vapid")
            return False
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {"p256dh": p256dh, "auth": auth},
                },
                data=json.dumps(payload),
                vapid_private_key=vapid_private,
                vapid_claims={"sub": f"mailto:{vapid_email}"},
            )
            return True
        except WebPushException as exc:  # type: ignore[misc]
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            if status in (404, 410):
                # Caller should mark token invalid.
                log.info("webpush.token_invalid", status=status)
                return False
            log.warning("webpush.failed", status=status, err=str(exc))
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("webpush.error", err=str(exc))
            return False
