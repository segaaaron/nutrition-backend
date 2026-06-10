"""F1 regression — spool failure isolation.

QA finding: if ``_spool_to_outbox`` raises (DB down, schema drift,
asyncio cancellation), the exception used to escape ``flush_request_scope``
and propagate through ``get_session`` / ``session_scope``, producing a
500 to the user AFTER the publisher's transaction had already committed.

Contract after fix:
- A handler raising during flush → spool attempt.
- Spool raises → log ``event_bus.spool_unrecoverable`` and SWALLOW.
- Flush completes without exception.
- Sibling handlers of the same event AND subsequent events still run.
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
class _Evt(DomainEvent):
    n: int


@pytest.mark.asyncio
async def test_spool_failure_does_not_propagate_out_of_flush(monkeypatch) -> None:
    async def exploding_spool(_event, _exc):
        raise RuntimeError("outbox table missing")

    monkeypatch.setattr("app.core.event_bus._spool_to_outbox", exploding_spool)

    # Intercept the structlog logger used by flush_request_scope so we
    # can assert the unrecoverable-spool log line was emitted.
    unrecoverable_logs: list[str] = []

    class _FakeLog:
        def exception(self, msg: str, **_kw) -> None:
            unrecoverable_logs.append(msg)

    import app.core.logging as logging_mod

    monkeypatch.setattr(logging_mod, "get_logger", lambda _name=None: _FakeLog())

    bus = EventBus()

    async def bad(_e: _Evt) -> None:
        raise ValueError("handler boom")

    bus.subscribe(_Evt, bad)

    token = begin_request_scope()
    await bus.publish(_Evt(n=1))

    # The contract: flush MUST NOT propagate. If this raises, F1 has
    # regressed and users see 500s on already-committed requests.
    await flush_request_scope(bus, token)

    assert "event_bus.spool_unrecoverable" in unrecoverable_logs, (
        "F1 regression: spool failure must emit the canonical "
        "'event_bus.spool_unrecoverable' log when the spool itself raises"
    )


@pytest.mark.asyncio
async def test_spool_failure_does_not_block_subsequent_events(monkeypatch) -> None:
    """If event 1's spool fails, event 2 must still dispatch."""

    async def exploding_spool(_event, _exc):
        raise RuntimeError("spool down")

    monkeypatch.setattr("app.core.event_bus._spool_to_outbox", exploding_spool)

    bus = EventBus()
    seen: list[int] = []

    async def maybe_bad(e: _Evt) -> None:
        if e.n == 1:
            raise ValueError("event 1 broke")
        seen.append(e.n)

    bus.subscribe(_Evt, maybe_bad)

    token = begin_request_scope()
    await bus.publish(_Evt(n=1))
    await bus.publish(_Evt(n=2))
    await flush_request_scope(bus, token)

    assert seen == [2], "event 2 must still run even if event 1's spool exploded"
