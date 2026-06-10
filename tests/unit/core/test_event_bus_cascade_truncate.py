"""F3 regression — cascade-event truncation on handler failure.

QA finding: a handler that publishes downstream events into the same
request scope AND THEN raises used to leave its cascade events in the
queue. Subsequent flush iterations dispatched those events even though
their causal trigger had failed → phantom side-effects (gamification
XP for an event the user never actually completed, etc).

Contract after fix:
- ``flush_request_scope`` snapshots ``len(queue)`` before each handler
  invocation.
- If the handler raises, any events appended in the failed window are
  spliced out of the queue.
- Those cascade events NEVER dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.event_bus import (
    DomainEvent,
    EventBus,
    begin_request_scope,
    flush_request_scope,
)


@dataclass(frozen=True, slots=True)
class _Trigger(DomainEvent):
    pass


@dataclass(frozen=True, slots=True)
class _Cascade(DomainEvent):
    note: str


@pytest.mark.asyncio
async def test_cascade_events_truncated_when_handler_raises(monkeypatch) -> None:
    async def fake_spool(_e, _x):
        return None

    monkeypatch.setattr("app.core.event_bus._spool_to_outbox", fake_spool)

    bus = EventBus()
    cascade_seen: list[str] = []

    async def trigger_handler(_e: _Trigger) -> None:
        # Publish a cascade BEFORE raising.
        await bus.publish(_Cascade(note="phantom"))
        raise RuntimeError("upstream failed")

    async def cascade_handler(e: _Cascade) -> None:
        cascade_seen.append(e.note)

    bus.subscribe(_Trigger, trigger_handler)
    bus.subscribe(_Cascade, cascade_handler)

    token = begin_request_scope()
    await bus.publish(_Trigger())
    await flush_request_scope(bus, token)

    assert cascade_seen == [], (
        "Cascade events published by a failing handler must be truncated "
        "from the queue — they have no causal trigger and dispatching "
        "them produces phantom side-effects."
    )


@pytest.mark.asyncio
async def test_successful_handler_cascade_still_dispatches(monkeypatch) -> None:
    """Counter-test: a healthy handler that publishes a cascade MUST
    still see the cascade fire. We only truncate when the publisher
    handler RAISED.
    """

    async def fake_spool(_e, _x):
        return None

    monkeypatch.setattr("app.core.event_bus._spool_to_outbox", fake_spool)

    bus = EventBus()
    seen: list[str] = []

    async def trigger_handler(_e: _Trigger) -> None:
        await bus.publish(_Cascade(note="legit"))

    async def cascade_handler(e: _Cascade) -> None:
        seen.append(e.note)

    bus.subscribe(_Trigger, trigger_handler)
    bus.subscribe(_Cascade, cascade_handler)

    token = begin_request_scope()
    await bus.publish(_Trigger())
    await flush_request_scope(bus, token)

    assert seen == ["legit"]
