"""FastAPI dependency wiring for runtime locale resolution.

This is the ONLY module in ``app/shared/i18n/`` that may import FastAPI
(per CLAUDE.md framework-agnosticism rule applied to shared/).

Resolution order (plan D1):

1. ``Accept-Language`` header (first supported tag).
2. ``profile.locale`` of the current authenticated user (if any).
3. ``"es"`` default (D4).

The profile lookup is a single indexed select; no JOINs. We swallow lookup
errors silently (translation is best-effort — must never break a request).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.shared.i18n.locale_resolver import Locale, resolve_locale


async def _get_session_i18n() -> AsyncIterator[AsyncSession]:
    """Private session dep. Duplicated from identity to avoid a circular
    import (identity.dependencies imports identity.use_cases which imports
    this package). Read-only locale lookup; no commit needed.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


_SessionDep = Annotated[AsyncSession, Depends(_get_session_i18n)]

_log = structlog.get_logger(__name__)

# Separate bearer instance with ``auto_error=False`` so anonymous endpoints
# (signup, public docs) don't 401 when calling :func:`get_locale`. We cannot
# reuse the identity-layer bearer because Depends caches the resolved value
# per scheme instance — sharing would couple anon locale resolution to the
# strict auth bearer.
_optional_bearer = HTTPBearer(auto_error=False)


async def _current_user_optional(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
) -> UUID | None:
    """Decode a JWT iff one is present; return ``None`` otherwise.

    Locale resolution must work for unauthenticated requests, so we never
    raise here. Any decode error is swallowed (caller falls back to the
    Accept-Language header or the ``"es"`` default).
    """
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    # Lazy import to avoid identity → i18n → identity circular import at boot.
    from app.identity.presentation.dependencies import get_jwt

    try:
        claims = await get_jwt().verify_access(creds.credentials)
    except Exception:  # noqa: BLE001 — best-effort, never break a request
        return None
    sub = claims.get("sub")
    if not sub:
        return None
    try:
        return UUID(str(sub))
    except ValueError:
        return None


async def _lookup_profile_locale(
    session: AsyncSession,
    user_id: UUID,
) -> str | None:
    """Best-effort single-row read of ``user_profiles.locale``."""
    try:
        row = (
            await session.execute(
                text("SELECT locale FROM user_profiles WHERE user_id = :uid"),
                {"uid": str(user_id)},
            )
        ).first()
    except Exception:  # noqa: BLE001 — translation must never break a request
        _log.warning("i18n.profile_lookup_failed", user_id=str(user_id))
        return None
    return None if row is None else str(row[0])


async def get_locale(
    session: _SessionDep,
    accept_language: Annotated[str | None, Header()] = None,
    user_id: Annotated[UUID | None, Depends(_current_user_optional)] = None,
) -> Locale:
    """Resolve the effective locale for the current request.

    Priority for authenticated users: profile.locale > Accept-Language > "es".
    Priority for anonymous users: Accept-Language > "es".

    profile.locale wins for authenticated users so that a LATAM user with
    an English-language device still receives Spanish content.
    """
    if user_id is not None:
        profile_locale = await _lookup_profile_locale(session, user_id)
        if profile_locale is not None:
            from app.shared.i18n.locale_resolver import _coerce_supported
            coerced = _coerce_supported(profile_locale)
            if coerced is not None:
                return coerced
    return resolve_locale(accept_language, None)


LocaleDep = Annotated[Locale, Depends(get_locale)]
"""Drop-in dependency for endpoints that emit user-facing strings.

Usage::

    @router.get("/plan/active")
    async def get_active_plan(locale: LocaleDep) -> PlanResponse: ...
"""
