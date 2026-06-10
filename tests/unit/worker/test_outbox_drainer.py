"""Drainer unit tests — replay path, backoff, dead-letter.

These tests target the pure logic surfaces of the drainer:
- ``_reconstruct``: EVENT_REGISTRY-driven event class lookup.
- ``_replay``: dispatches a reconstructed event through the bus.
- ``_backoff_seconds``: exponential capped backoff curve.

End-to-end SQL behaviour (FOR UPDATE SKIP LOCKED, dispatched_at,
attempts bookkeeping) lives in
``tests/integration/core/test_outbox_drainer_pg.py`` — gated on Docker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import (
    DomainEvent,
    EVENT_REGISTRY,
    EventBus,
    ensure_event_registry_bootstrapped,
    event_type_name,
    register_event,
    reset_event_bus_for_tests,
)
from worker.outbox_drainer import (
    _BACKOFF_CAP_SECONDS,
    _backoff_seconds,
    _reconstruct,
    _replay,
)


@dataclass(frozen=True, slots=True)
class _DrainerProbe(DomainEvent):
    """Test-only event with a stable canonical name. Registered eagerly
    so ``_reconstruct`` can find it.
    """

    user_id: UUID
    note: str


# Register at import — idempotent on test re-runs.
register_event(_DrainerProbe)


def test_event_registry_contains_probe() -> None:
    assert EVENT_REGISTRY[event_type_name(_DrainerProbe)] is _DrainerProbe


def test_reconstruct_known_event_returns_typed_instance() -> None:
    uid = uuid4()
    evt = _reconstruct(
        event_type_name(_DrainerProbe),
        {"user_id": str(uid), "note": "hello"},
    )
    assert isinstance(evt, _DrainerProbe)
    # NOTE: dataclasses do not coerce; the drainer stores stringified
    # UUIDs and the receiving handler is responsible for coercion if
    # it needs a typed UUID. For replay parity we accept the payload
    # as-stored.
    assert evt.note == "hello"


def test_reconstruct_unknown_event_returns_none() -> None:
    assert _reconstruct("not.a.real.Event", {}) is None


@pytest.mark.asyncio
async def test_replay_dispatches_through_bus(monkeypatch) -> None:
    reset_event_bus_for_tests()
    from app.core.event_bus import get_event_bus

    bus = get_event_bus()
    seen: list[str] = []

    async def handler(e: _DrainerProbe) -> None:
        seen.append(e.note)

    bus.subscribe(_DrainerProbe, handler)

    await _replay(
        event_type_name(_DrainerProbe),
        {"user_id": str(uuid4()), "note": "replayed"},
    )

    assert seen == ["replayed"]
    reset_event_bus_for_tests()


@pytest.mark.asyncio
async def test_replay_unknown_event_raises_lookup_error() -> None:
    with pytest.raises(LookupError) as exc_info:
        await _replay("ghost.Event", {"x": 1})
    assert "unknown_event_type" in str(exc_info.value)


@pytest.mark.asyncio
async def test_replay_payload_shape_mismatch_raises() -> None:
    """Constructor signature mismatch must propagate so the drainer
    counts a failed attempt and bumps backoff.
    """
    with pytest.raises(TypeError):
        await _replay(
            event_type_name(_DrainerProbe),
            {"wrong_field": 1},
        )


def test_backoff_grows_exponentially_and_caps_at_30min() -> None:
    # 2^1=2, 2^2=4, 2^3=8, ... growing geometrically until the cap.
    assert _backoff_seconds(1) == 2
    assert _backoff_seconds(2) == 4
    assert _backoff_seconds(3) == 8
    # Cap reached at attempt 11 (2^11 = 2048 > 1800) — verify cap holds
    # from there forward.
    assert _backoff_seconds(11) == _BACKOFF_CAP_SECONDS == 30 * 60
    assert _backoff_seconds(20) == _BACKOFF_CAP_SECONDS  # still capped
    # Strict monotonic growth up to the cap.
    assert _backoff_seconds(5) > _backoff_seconds(4) > _backoff_seconds(3)


def test_event_registry_covers_all_known_domain_event_subclasses() -> None:
    """Discovery enforcement — every DomainEvent subclass reachable
    through the standard import map must be in EVENT_REGISTRY. If this
    fails, a new event was added without updating
    ``_bootstrap_event_registry`` in ``app/core/event_bus.py``.
    """
    # Trigger imports of every module in the bootstrap list AND run
    # the deferred bootstrap so the registry is populated.
    import importlib

    ensure_event_registry_bootstrapped()

    bootstrap_modules = (
        "app.identity.domain.events",
        "app.profile.domain.events",
        "app.plan.domain.events",
        "app.tracking.domain.events",
        "app.tracking.domain.fasting",
        "app.vision.domain.events",
        "app.coach.domain.events",
        "app.gamification.domain.events",
        "app.recipes.domain.events",
        "app.billing.domain",
        "app.nutrition.event_handlers",
    )

    expected: set[str] = set()
    for modname in bootstrap_modules:
        m = importlib.import_module(modname)
        for attr in vars(m).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, DomainEvent)
                and attr is not DomainEvent
                and attr.__module__ == m.__name__
            ):
                expected.add(event_type_name(attr))

    missing = expected - set(EVENT_REGISTRY.keys())
    if missing:
        # Diagnostic: dump registry contents to ease triage of order-
        # dependent failures.
        present = sorted(EVENT_REGISTRY.keys())
        raise AssertionError(
            f"DomainEvent subclasses missing from EVENT_REGISTRY: "
            f"{sorted(missing)}.\nRegistry has {len(present)} entries: "
            f"{present}\nExpected {len(expected)}: {sorted(expected)}"
        )
