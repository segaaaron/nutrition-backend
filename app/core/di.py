"""Dependency-injection wiring. Per-context providers register here so
presentation routers can `Depends(...)` without importing infrastructure
directly.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.shared.domain.email_sender import EmailSender

log = get_logger("core.di")


# NOTE: a previous ``get_session`` lived here. It was DEAD CODE — no
# router imported it (only ``app.identity.presentation.dependencies
# .get_session`` is wired into ``SessionDep``). The stale duplicate
# did NOT begin a deferred event scope and did NOT commit, so any code
# that started to depend on it would silently lose writes and never
# dispatch domain events. Removed in the Patrón #3 audit pass.


@lru_cache(maxsize=1)
def get_email_sender() -> EmailSender:
    """Process-wide singleton.

    Decision matrix:
      - email_enabled=false → NullEmailSender (no-op + log)
      - email_enabled=true  + resend_api_key empty → NullEmailSender (no-op + warning)
      - email_enabled=true  + key present → ResendEmailSender
    """
    # Imported lazily so the domain layer never transitively imports httpx.
    from app.notifications.infrastructure.null_sender import NullEmailSender
    from app.notifications.infrastructure.resend_sender import ResendEmailSender

    s = get_settings()
    if not s.email_enabled:
        return NullEmailSender()
    if not s.resend_api_key:
        # NOTE: log key avoids the PII token "email" (see scripts/pii_log_grep
        # banned tokens). This is an infra config warning, not a PII payload.
        log.warning("notifications.sender.resend_key_missing", reason="resend_api_key_missing")
        return NullEmailSender()
    return ResendEmailSender(api_key=s.resend_api_key)
