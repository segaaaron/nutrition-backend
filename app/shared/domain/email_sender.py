"""Email sender port (framework-agnostic).

Domain layer contract for sending transactional email. Implementations live
in infrastructure (Resend adapter, null adapter). Use cases depend on this
Protocol and stay decoupled from HTTP libraries.
"""

from __future__ import annotations

from typing import Protocol

from app.core.errors import UpstreamError


class EmailDeliveryError(UpstreamError):
    """Raised when an email cannot be delivered by the upstream provider.

    Carries a sanitized ``detail`` (no API key, no PII). Mapped to HTTP 502
    by the global problem-details handler.
    """

    type_slug = "email-delivery"
    title = "Email delivery failed"


class EmailSender(Protocol):
    """Send a single transactional email.

    Implementations MUST be async, MUST NOT leak the API key in logs or
    exception messages, and MUST NOT log the raw recipient address (hash
    or redact instead — GDPR/LGPD PII minimisation).
    """

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> None:
        """Deliver the email. Raises :class:`EmailDeliveryError` on failure."""
        ...
