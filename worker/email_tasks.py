"""Arq tasks for transactional email dispatch.

Status (2026-06-04): currently UNUSED from ``/v1/identity/otp/send``.
Closed-beta (<=100 users) uses INLINE dispatch inside the ``SendOtp`` use
case. Registered for future migration when the OTP endpoint p95 degrades
(>300ms), users report perceptible delay, OR Resend rate-limits are hit
(>100 emails/min sustained). See ``SendOtp`` docstring for the full
rationale and migration trigger criteria.

Why a worker? Email sends are non-critical-path I/O. Off-loading from the
request thread keeps p95 of the OTP endpoint flat regardless of Resend
latency and lets us retry transparently on transient provider errors.

Idempotency: Arq jobs already carry a unique ``job_id``. We pass it through
to the Resend ``Idempotency-Key`` header so a worker retry never produces a
duplicate send.

Retry policy: Arq's default ``max_tries=3`` is honoured. The ResendEmail-
Sender itself does intra-call exponential backoff on transient HTTP errors
(429/5xx), so a job retry only kicks in for crashes or terminal failures.
"""

from __future__ import annotations

from typing import Any

from app.core.di import get_email_sender
from app.core.logging import get_logger
from app.shared.domain.email_sender import EmailDeliveryError

log = get_logger("worker.email")


async def send_email_task(  # noqa: PLR0913  (Arq task fan-out args)
    ctx: dict[str, Any],
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    """Dispatch a single email via the configured EmailSender.

    Returns ``{"status": "sent"}`` on success or ``{"status": "skipped"}``
    when the sender is a no-op (EMAIL_ENABLED=false). Raises
    ``EmailDeliveryError`` on terminal failure so Arq schedules a retry.
    """
    sender = get_email_sender()
    job_id = ctx.get("job_id")
    key = idempotency_key or (str(job_id) if job_id else None)
    try:
        await sender.send(
            to=to, subject=subject, html=html, text=text, idempotency_key=key
        )
    except EmailDeliveryError:
        log.warning("worker.mail.failed", job_id=str(job_id) if job_id else None)
        raise
    return {"status": "sent"}
