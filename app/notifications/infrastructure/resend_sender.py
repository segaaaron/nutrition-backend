"""Resend (https://resend.com/) email adapter.

Implements :class:`app.shared.domain.email_sender.EmailSender` via the
Resend REST API. Network discipline:

- async-only (``httpx.AsyncClient``)
- 5 s connect+read timeout (default; overridable in ctor)
- exponential backoff on 429 / 5xx (3 attempts: 0.5 s, 1.0 s, 2.0 s)
- ``Idempotency-Key`` header derived from caller-provided key (default
  ``uuid4()``); Resend deduplicates identical bodies within 24 h
- structured logging via ``structlog`` — recipient is hashed (SHA-256, 16
  hex chars), API key never logged, response body redacted to ``status``
- raises :class:`EmailDeliveryError` with a sanitized detail on terminal
  failure (auth, validation, retries exhausted)
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Final
from uuid import uuid4

import httpx
import structlog

from app.shared.domain.email_sender import EmailDeliveryError, EmailSender

_log = structlog.get_logger(__name__)

_RESEND_ENDPOINT: Final[str] = "https://api.resend.com/emails"
_MAX_ATTEMPTS: Final[int] = 3
_BACKOFF_BASE_S: Final[float] = 0.5
_RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})
# NOVA brand sender. Invariant across dev/staging/prod — domain ownership
# does not change per environment, so this lives in code, not env config.
# DNS (SPF + DKIM) for ms-tech-stack.cloud must be configured in Resend.
_FROM_EMAIL: Final[str] = "no-reply@ms-tech-stack.cloud"


def _hash_recipient(addr: str) -> str:
    return hashlib.sha256(addr.strip().lower().encode("utf-8")).hexdigest()[:16]


class ResendEmailSender(EmailSender):
    """Resend adapter. Construct once per process (httpx client is reused)."""

    __slots__ = ("_api_key", "_client", "_owns_client")

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not api_key:
            # Fail-loud: caller must guard at factory level; never construct
            # with an empty key in production.
            raise ValueError("ResendEmailSender requires a non-empty api_key")
        self._api_key = api_key
        if client is None:
            self._client = httpx.AsyncClient(timeout=timeout_seconds)
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> None:
        key = idempotency_key or str(uuid4())
        payload: dict[str, object] = {
            "from": _FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": key,
            "Content-Type": "application/json",
        }
        to_hash = _hash_recipient(to)

        last_status: int | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await self._client.post(
                    _RESEND_ENDPOINT, json=payload, headers=headers
                )
            except httpx.HTTPError as exc:
                # Network / timeout / DNS — retry while attempts remain.
                _log.warning(
                    "mail.transport_error",
                    to_hash=to_hash,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                )
                if attempt == _MAX_ATTEMPTS:
                    raise EmailDeliveryError("email_transport_error") from exc
                await asyncio.sleep(_BACKOFF_BASE_S * (2 ** (attempt - 1)))
                continue

            last_status = resp.status_code
            if 200 <= resp.status_code < 300:
                _log.info(
                    "mail.sent",
                    provider="resend",
                    to_hash=to_hash,
                    subject=subject,
                    status=resp.status_code,
                    attempt=attempt,
                )
                return

            if resp.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
                _log.warning(
                    "mail.retryable_status",
                    to_hash=to_hash,
                    status=resp.status_code,
                    attempt=attempt,
                )
                await asyncio.sleep(_BACKOFF_BASE_S * (2 ** (attempt - 1)))
                continue

            # Terminal non-retryable failure (4xx other than 408/429) or
            # retries exhausted on a retryable status.
            _log.error(
                "mail.failed",
                to_hash=to_hash,
                status=resp.status_code,
                attempt=attempt,
            )
            raise EmailDeliveryError(f"email_provider_status_{resp.status_code}")

        # Loop fell through without returning — defensive (shouldn't happen).
        raise EmailDeliveryError(  # pragma: no cover
            f"email_retries_exhausted_status_{last_status}"
        )
