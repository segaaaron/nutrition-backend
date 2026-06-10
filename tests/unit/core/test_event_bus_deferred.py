"""Regression suite for ADR-0030 — Event Publishing Pattern.

These tests pin the deferred-publish + post-commit-dispatch contract of
``app.core.event_bus``. They MUST stay green; if they fail, the cross-
session race that produced empty plan_meals (and other silent handler
no-ops) has come back.

Coverage:

1. ``EventBus`` in **immediate mode** (no request scope) dispatches on
   ``publish`` and ``publish_many`` synchronously — preserves the
   pre-ADR contract used by unit tests.
2. Inside a request scope ``publish`` is deferred until
   ``flush_request_scope`` runs.
3. ``discard_request_scope`` drops the queue without dispatching
   (rollback path).
4. A handler that raises during post-commit dispatch DOES NOT abort the
   loop and DOES NOT propagate — siblings still run.
5. ``publish_many`` routes through ``publish`` in immediate mode so spy
   subclasses see every event (regression for ``_SpyBus`` pattern in
   ``test_complete_onboarding``).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.event_bus import (
    DomainEvent,
    EventBus,
    begin_request_scope,
    discard_request_scope,
    flush_request_scope,
    is_request_scope_active,
)


@dataclass(frozen=True, slots=True)
class _Evt(DomainEvent):
    n: int


@pytest.mark.asyncio
async def test_immediate_mode_publishes_synchronously() -> None:
    bus = EventBus()
    seen: list[int] = []

    async def handler(e: _Evt) -> None:
        seen.append(e.n)

    bus.subscribe(_Evt, handler)
    await bus.publish(_Evt(n=1))
    await bus.publish_many([_Evt(n=2), _Evt(n=3)])

    assert seen == [1, 2, 3]


@pytest.mark.asyncio
async def test_publish_many_routes_through_publish_for_spies() -> None:
    """Regression: a subclass that overrides only ``publish`` must still
    see events emitted via ``publish_many``."""

    seen: list[int] = []

    class Spy(EventBus):
        async def publish(self, event: DomainEvent) -> None:  # type: ignore[override]
            assert isinstance(event, _Evt)
            seen.append(event.n)
            await super().publish(event)

    bus = Spy()
    await bus.publish_many([_Evt(n=10), _Evt(n=20)])
    assert sorted(seen) == [10, 20]


@pytest.mark.asyncio
async def test_request_scope_defers_dispatch_until_flush() -> None:
    bus = EventBus()
    seen: list[int] = []

    async def handler(e: _Evt) -> None:
        seen.append(e.n)

    bus.subscribe(_Evt, handler)

    assert not is_request_scope_active()
    token = begin_request_scope()
    assert is_request_scope_active()

    await bus.publish(_Evt(n=1))
    await bus.publish_many([_Evt(n=2), _Evt(n=3)])
    assert seen == [], "publish must not dispatch while scope is open"

    await flush_request_scope(bus, token)
    assert seen == [1, 2, 3], "flush must dispatch queued events in order"
    assert not is_request_scope_active()


@pytest.mark.asyncio
async def test_discard_request_scope_drops_queue() -> None:
    bus = EventBus()
    seen: list[int] = []

    async def handler(e: _Evt) -> None:
        seen.append(e.n)

    bus.subscribe(_Evt, handler)

    token = begin_request_scope()
    await bus.publish(_Evt(n=99))
    discard_request_scope(token)

    assert seen == [], "discarded scope must not dispatch"
    assert not is_request_scope_active()


@pytest.mark.asyncio
async def test_failing_handler_does_not_block_siblings_in_flush(monkeypatch) -> None:
    """A handler that raises during post-commit dispatch must be isolated
    so subsequent events still run. The failure goes to the outbox
    spool (mocked here to a list)."""

    spooled: list[tuple[str, str]] = []

    async def fake_spool(event, exc):
        spooled.append((type(event).__name__, type(exc).__name__))

    monkeypatch.setattr("app.core.event_bus._spool_to_outbox", fake_spool)

    bus = EventBus()
    seen: list[int] = []

    async def bad(_e: _Evt) -> None:
        raise RuntimeError("boom")

    async def good(e: _Evt) -> None:
        seen.append(e.n)

    bus.subscribe(_Evt, bad)
    bus.subscribe(_Evt, good)

    token = begin_request_scope()
    await bus.publish(_Evt(n=1))
    await bus.publish(_Evt(n=2))
    # flush must not raise even though `bad` does.
    await flush_request_scope(bus, token)

    # Per-handler isolation: `good` runs for BOTH events even though
    # `bad` raised on each. `bad` failures are spooled to outbox.
    assert sorted(seen) == [1, 2]
    assert len(spooled) == 2
    assert all(s[0] == "_Evt" and s[1] == "RuntimeError" for s in spooled)


@pytest.mark.asyncio
async def test_handler_sees_committed_state_regression() -> None:
    """ADR-0030 regression: simulate the empty-plan_meals bug.

    Reproduces the canonical failure mode:
      - Publisher writes row R inside an active session that has NOT
        yet committed.
      - Publisher emits an event.
      - Handler opens a fresh "session" (modelled here as a dict view
        of committed state) and reads R.

    BEFORE ADR-0030: handler ran inside ``publish`` (before commit) and
    saw an empty view → silent no-op.
    AFTER ADR-0030: handler runs in ``flush_request_scope`` (after
    commit) and sees R.
    """
    committed: dict[str, int] = {}
    uncommitted: dict[str, int] = {}

    async def publisher_use_case(bus: EventBus) -> None:
        # Mimic SQLAlchemy: write goes to the active tx, NOT yet visible.
        uncommitted["goals"] = 2000
        await bus.publish(_Evt(n=1))

    seen_by_handler: dict[str, int | None] = {}

    async def handler(_e: _Evt) -> None:
        # Mimic ``async with session_scope() as s: s.execute(SELECT ...)``
        # — a fresh session only sees rows that are committed.
        seen_by_handler["goals"] = committed.get("goals")

    bus = EventBus()
    bus.subscribe(_Evt, handler)

    token = begin_request_scope()
    try:
        await publisher_use_case(bus)
        # "commit" — copy uncommitted view into the committed snapshot.
        committed.update(uncommitted)
    except Exception:
        discard_request_scope(token)
        raise
    else:
        await flush_request_scope(bus, token)

    assert seen_by_handler["goals"] == 2000, (
        "handler must observe committed data after flush — this is the "
        "exact property whose absence caused empty plan_meals"
    )
