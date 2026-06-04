"""No-op email sender (used when EMAIL_ENABLED=false or RESEND_API_KEY empty).

Logs a structured ``email.skipped`` event with a hashed recipient so we can
correlate operationally without storing PII. Never raises.
"""

from __future__ import annotations

import hashlib

import structlog

from app.shared.domain.email_sender import EmailSender

_log = structlog.get_logger(__name__)


def _hash_recipient(addr: str) -> str:
    return hashlib.sha256(addr.strip().lower().encode("utf-8")).hexdigest()[:16]


class NullEmailSender(EmailSender):
    """No-op implementation; safe default for dev/test/closed-beta."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,  # noqa: ARG002  (interface compliance)
        text: str,  # noqa: ARG002
        idempotency_key: str | None = None,
    ) -> None:
        _log.info(
            "mail.skipped",
            reason="mail_disabled",
            to_hash=_hash_recipient(to),
            subject=subject,
            idempotency_key=idempotency_key,
        )
