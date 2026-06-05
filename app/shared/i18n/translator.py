"""Translator: lookup ``i18n_translations(scope, key, locale, value)`` with
Redis cache + locale-fallback chain.

Uses the existing table from migration 0001 (D7). NO new schema.

Cache contract:

* Key: ``"i18n:{scope}:{key}:{locale}"`` (Redis flat namespace).
* TTL: 3600s (steady-state hit rate target ≥95% per Phase 8.4).
* Sentinel for misses: ``"\\x00"`` — 1 byte, distinct from any real value
  (real values are user-facing UTF-8 strings, never NUL).
* Invalidation: manual ``DEL i18n:*`` (TTL bounds staleness to 1h).

Fallback chain on miss (D9 KISS):

1. Requested ``locale`` row in DB.
2. ``"es"`` row in DB (canonical fallback, D4 LatAm-first).
3. Raw ``key`` (loud warning log — caller forgot to seed).

Format kwargs use ``str.format``. We reject templates containing unmatched
braces (mitigation §7 — email XSS by malformed kwargs). Empty kwargs skip
formatting entirely (cheaper, also avoids ``{0}``-style ambiguity).
"""

from __future__ import annotations

from typing import Final, Protocol

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.i18n.locale_resolver import Locale

_log = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS: Final[int] = 3600
_MISS_SENTINEL: Final[str] = "\x00"
_FALLBACK_LOCALE: Final[Locale] = "es"


class TranslatorProtocol(Protocol):
    """Structural type for use cases / domain code that need translation.

    Domain layer depends on this Protocol (DIP), never on the concrete
    :class:`Translator`. Tests substitute an in-memory fake.
    """

    async def translate(
        self,
        scope: str,
        key: str,
        locale: Locale,
        /,
        **kwargs: object,
    ) -> str: ...


def _has_balanced_braces(template: str) -> bool:
    """True when every ``{`` has a matching ``}`` in left-to-right order.

    Treats ``{{`` and ``}}`` as literal escapes per :py:meth:`str.format`.
    """
    depth = 0
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch == "{":
            if i + 1 < n and template[i + 1] == "{":
                i += 2
                continue
            depth += 1
        elif ch == "}":
            if i + 1 < n and template[i + 1] == "}":
                i += 2
                continue
            if depth == 0:
                return False
            depth -= 1
        i += 1
    return depth == 0


class Translator:
    """Stateful Translator bound to a request scope (session + redis).

    SRP — owns *only* lookup + cache + fallback. Does not resolve locales
    (see :func:`app.shared.i18n.locale_resolver.resolve_locale`).
    """

    __slots__ = ("_redis", "_session")

    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis

    async def translate(
        self,
        scope: str,
        key: str,
        locale: Locale,
        /,
        **kwargs: object,
    ) -> str:
        """Return the localised string for ``(scope, key, locale)``.

        Args:
            scope: Logical namespace (e.g. ``"errors"``, ``"coach"``).
            key: Stable identifier within scope (canonical EN snake_case).
            locale: Target locale, must be in :data:`SUPPORTED_LOCALES`.
            **kwargs: Optional :py:meth:`str.format` substitutions.

        Returns:
            Localised string (after format substitution when kwargs given).
            On total miss returns ``key`` itself and logs a warning.
        """
        template = await self._lookup_with_fallback(scope, key, locale)
        if not kwargs:
            return template
        if not _has_balanced_braces(template):
            _log.warning(
                "i18n.unbalanced_braces",
                scope=scope,
                key=key,
                locale=locale,
            )
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError) as exc:
            _log.warning(
                "i18n.format_error",
                scope=scope,
                key=key,
                locale=locale,
                error=str(exc),
            )
            return template

    async def _lookup_with_fallback(
        self,
        scope: str,
        key: str,
        locale: Locale,
    ) -> str:
        # Primary locale.
        value = await self._lookup_cached(scope, key, locale)
        if value is not None:
            return value
        # Spanish canonical fallback (D4).
        if locale != _FALLBACK_LOCALE:
            value = await self._lookup_cached(scope, key, _FALLBACK_LOCALE)
            if value is not None:
                return value
        # Total miss — loud warning + key echo.
        _log.warning(
            "i18n.missing_translation",
            scope=scope,
            key=key,
            locale=locale,
        )
        return key

    async def _lookup_cached(
        self,
        scope: str,
        key: str,
        locale: Locale,
    ) -> str | None:
        cache_key = f"i18n:{scope}:{key}:{locale}"
        cached = await self._redis.get(cache_key)
        if cached is not None:
            return None if cached == _MISS_SENTINEL else cached
        value = await self._lookup_db(scope, key, locale)
        await self._redis.set(
            cache_key,
            value if value is not None else _MISS_SENTINEL,
            ex=_CACHE_TTL_SECONDS,
        )
        return value

    async def _lookup_db(
        self,
        scope: str,
        key: str,
        locale: Locale,
    ) -> str | None:
        row = (
            await self._session.execute(
                text(
                    "SELECT value FROM i18n_translations "
                    "WHERE scope = :scope AND key = :key AND locale = :locale"
                ),
                {"scope": scope, "key": key, "locale": locale},
            )
        ).first()
        return None if row is None else str(row[0])
