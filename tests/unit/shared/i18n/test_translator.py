"""Unit tests for :class:`app.shared.i18n.translator.Translator`.

Use lightweight in-memory fakes for Redis + AsyncSession to keep these
tests at the unit tier (no testcontainers). Behaviour covered:

* DB hit + cached on subsequent calls.
* Cache miss sentinel prevents repeated DB hits on absent keys.
* Fallback chain: locale -> "es" -> raw key.
* ``str.format`` kwargs applied correctly.
* Templates with unbalanced braces return raw (no exception).
* Missing format kwargs return raw template (no exception).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.shared.i18n.translator import Translator

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async Redis stand-in: ``get`` + ``set`` only."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls += 1
        self.store[key] = value


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class FakeSession:
    """In-memory ``(scope, key, locale) -> value`` lookup."""

    def __init__(self, rows: dict[tuple[str, str, str], str]) -> None:
        self._rows = rows
        self.exec_calls: list[dict[str, Any]] = []

    async def execute(self, _stmt: Any, params: dict[str, Any]) -> _FakeResult:
        self.exec_calls.append(params)
        key = (params["scope"], params["key"], params["locale"])
        if key in self._rows:
            return _FakeResult((self._rows[key],))
        return _FakeResult(None)


def _make(
    rows: dict[tuple[str, str, str], str] | None = None,
) -> tuple[Translator, FakeRedis, FakeSession]:
    redis = FakeRedis()
    session = FakeSession(rows or {})
    # The Translator only touches .execute on the session and .get/.set on
    # redis — both satisfied by structural typing. Casts silence mypy.
    return (
        Translator(session=session, redis=redis),  # type: ignore[arg-type]
        redis,
        session,
    )


# ---------------------------------------------------------------------------
# Cache + DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_hit_returns_value_and_populates_cache() -> None:
    t, redis, session = _make({("errors", "not_found", "en"): "Not found"})
    out = await t.translate("errors", "not_found", "en")
    assert out == "Not found"
    assert redis.store["i18n:errors:not_found:en"] == "Not found"
    assert len(session.exec_calls) == 1


@pytest.mark.asyncio
async def test_second_call_served_from_cache() -> None:
    t, _redis, session = _make({("errors", "not_found", "en"): "Not found"})
    await t.translate("errors", "not_found", "en")
    await t.translate("errors", "not_found", "en")
    assert len(session.exec_calls) == 1


@pytest.mark.asyncio
async def test_miss_sentinel_prevents_repeated_db_lookups() -> None:
    t, _redis, session = _make({})
    await t.translate("errors", "ghost", "en")
    await t.translate("errors", "ghost", "en")
    # Lookups: en miss + es fallback miss on first call only.
    # Second call: en sentinel hit + es sentinel hit -> 0 new DB calls.
    assert len(session.exec_calls) == 2


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_to_es_when_target_locale_missing() -> None:
    t, _redis, _session = _make({("errors", "boom", "es"): "Explosión"})
    out = await t.translate("errors", "boom", "en")
    assert out == "Explosión"


@pytest.mark.asyncio
async def test_total_miss_returns_key_unchanged() -> None:
    t, _redis, _session = _make({})
    out = await t.translate("errors", "ghost_key", "en")
    assert out == "ghost_key"


@pytest.mark.asyncio
async def test_es_locale_does_not_double_lookup() -> None:
    t, _redis, session = _make({})
    await t.translate("errors", "ghost", "es")
    # Only one lookup: es. No redundant es-fallback.
    assert len(session.exec_calls) == 1


# ---------------------------------------------------------------------------
# Format kwargs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_kwargs_applied() -> None:
    t, _redis, _session = _make(
        {("coach", "greet", "en"): "Hello, {name}!"},
    )
    out = await t.translate("coach", "greet", "en", name="Miguel")
    assert out == "Hello, Miguel!"


@pytest.mark.asyncio
async def test_unbalanced_braces_returns_raw() -> None:
    t, _redis, _session = _make(
        {("errors", "bad", "en"): "broken {only_open"},
    )
    out = await t.translate("errors", "bad", "en", x="y")
    assert out == "broken {only_open"


@pytest.mark.asyncio
async def test_escaped_braces_are_treated_as_balanced() -> None:
    t, _redis, _session = _make(
        {("errors", "ok", "en"): "literal {{ and }} fine {x}"},
    )
    out = await t.translate("errors", "ok", "en", x="value")
    assert out == "literal { and } fine value"


@pytest.mark.asyncio
async def test_missing_kwarg_does_not_raise() -> None:
    t, _redis, _session = _make(
        {("errors", "needs", "en"): "Hello {missing}"},
    )
    out = await t.translate("errors", "needs", "en", other="x")
    # Returns raw template (loud-warn logged) — never crashes the request.
    assert out == "Hello {missing}"


@pytest.mark.asyncio
async def test_no_kwargs_skips_format_for_template_with_braces() -> None:
    # When caller passes no kwargs we don't invoke .format at all — so a
    # legitimate ``{x}`` placeholder stays literal.
    t, _redis, _session = _make({("ui", "tpl", "en"): "raw {x} stays"})
    out = await t.translate("ui", "tpl", "en")
    assert out == "raw {x} stays"


@pytest.mark.asyncio
async def test_fallback_chain_does_not_widen_unsupported_lookups() -> None:
    # Confirm we only ever lookup the requested locale + "es" — never "en"
    # as a tertiary fallback (D9 KISS).
    t, _redis, session = _make({})
    await t.translate("errors", "x", "en")
    locales: Sequence[str] = [c["locale"] for c in session.exec_calls]
    assert sorted(set(locales)) == ["en", "es"]
