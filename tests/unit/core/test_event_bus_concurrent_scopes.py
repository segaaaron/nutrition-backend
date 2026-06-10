"""F8 regression — ContextVar isolation across concurrent request scopes.

``asyncio.gather`` runs N coroutines in the same event-loop; each one
opens its own ``begin_request_scope`` and must observe ONLY its own
events at flush time. If the deferred queue were process-global (a
list) instead of ContextVar-scoped, cross-request contamination would
fail this test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.core.event_bus import (
    DomainEvent,
    EventBus,
    begin_request_scope,
    flush_request_scope,
)


@dataclass(frozen=True, slots=True)
class _ScopedEvent(DomainEvent):
    scope_id: int
    seq: int


@pytest.mark.asyncio
async def test_concurrent_scopes_do_not_leak_events(monkeypatch) -> None:
    async def fake_spool(_e, _x):
        return None

    monkeypatch.setattr("app.core.event_bus._spool_to_outbox", fake_spool)

    bus = EventBus()
    per_scope_observed: dict[int, list[int]] = {}

    async def handler(e: _ScopedEvent) -> None:
        per_scope_observed.setdefault(e.scope_id, []).append(e.seq)

    bus.subscribe(_ScopedEvent, handler)

    async def one_scope(scope_id: int) -> None:
        token = begin_request_scope()
        # Yield between publishes so the scheduler is forced to
        # interleave coroutines — this is the actual stress for
        # ContextVar isolation.
        for seq in range(5):
            await bus.publish(_ScopedEvent(scope_id=scope_id, seq=seq))
            await asyncio.sleep(0)
        await flush_request_scope(bus, token)

    await asyncio.gather(*(one_scope(i) for i in range(100)))

    assert len(per_scope_observed) == 100, "every scope must have flushed"
    for scope_id, seqs in per_scope_observed.items():
        # Critical assertion: ONLY this scope's seqs, no cross-talk.
        assert seqs == [0, 1, 2, 3, 4], (
            f"scope {scope_id} saw {seqs} — ContextVar isolation broken; "
            "events leaked between concurrent request scopes"
        )
