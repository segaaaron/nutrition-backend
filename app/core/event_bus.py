"""In-process domain event dispatcher with post-commit semantics.

Two modes coexist:

1. **Immediate mode** (default, used by unit tests that instantiate
   ``EventBus()`` directly): handlers fire synchronously on publish.
   Backwards-compatible with the original contract.

2. **Deferred mode** (engaged by ``begin_request_scope()``): publishes
   are queued in a ``ContextVar`` and dispatched only after the caller
   explicitly calls ``flush_request_scope()`` — which happens after
   ``session.commit()`` in ``get_session`` / ``session_scope``.

Why deferred? Because handlers commonly open a fresh ``session_scope``
to read data the publisher just wrote. If the publish runs BEFORE the
publisher's session commits, the handler's session — which begins a
fresh snapshot — does NOT see the row, and the handler silently
no-ops (see ADR-0030). Deferring the dispatch until after commit
eliminates the cross-session race.

Failure handling (ADR-0030 §Failure Modes):

- Per-handler isolation in the flush loop — one failing handler does
  not starve siblings.
- Handler failures during post-commit dispatch are serialised to the
  ``outbox`` table (best-effort spool). The outbox drainer worker
  reconstructs the event via ``EVENT_REGISTRY`` and replays it.
- If the spool itself raises (DB down, schema drift, asyncio cancel),
  the bus logs ``event_bus.spool_unrecoverable`` and SWALLOWS the
  exception. The publisher's transaction is already committed; never
  propagate a downstream failure into the user-visible response
  (regression F1 — QA HIGH).
- If a handler raises AFTER publishing cascade events into the same
  request scope, those cascade events are TRUNCATED from the queue
  so we never dispatch side-effects whose triggering event failed
  (regression F3 — QA HIGH).

ADR-0030: Event Publishing Pattern.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

Handler = Callable[[Any], Optional[Awaitable[None]]]


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Marker base. Subclass with frozen dataclasses."""


# --------------------------------------------------------------------------- #
# Canonical event type naming                                                  #
# --------------------------------------------------------------------------- #


def event_type_name(cls: type[DomainEvent]) -> str:
    """Canonical wire name for a DomainEvent subclass.

    Module-qualified (``"app.tracking.domain.events.WeightLogged"``) to
    disambiguate collisions like ``plan.DayCompleted`` vs
    ``gamification.DayCompleted`` and ``tracking.WeightLogged`` vs
    ``nutrition.event_handlers.WeightLogged`` (the latter is a local
    re-declaration; both must remain replayable independently).
    """
    return f"{cls.__module__}.{cls.__qualname__}"


# --------------------------------------------------------------------------- #
# EVENT_REGISTRY — discovery-driven replay map for the outbox drainer         #
# --------------------------------------------------------------------------- #


EVENT_REGISTRY: dict[str, type[DomainEvent]] = {}

_BOOTSTRAPPED = False


def register_event(cls: type[DomainEvent]) -> type[DomainEvent]:
    """Register a DomainEvent class so the outbox drainer can reconstruct
    it from a persisted payload.

    Idempotent: re-registering the same class is a no-op; registering a
    DIFFERENT class under the same canonical name raises (collision
    safety).
    """
    name = event_type_name(cls)
    existing = EVENT_REGISTRY.get(name)
    if existing is cls:
        return cls
    if existing is not None:
        raise RuntimeError(
            f"EVENT_REGISTRY collision: {name} already bound to {existing!r}"
        )
    EVENT_REGISTRY[name] = cls
    return cls


def ensure_event_registry_bootstrapped() -> None:
    """Idempotent on-demand bootstrap. Importing all event modules at
    module-load time triggers circular imports (event modules import
    ``DomainEvent`` from this module → re-entry during bootstrap
    sees a partial module with no classes defined yet → registration
    misses entries). Deferring to first consumer (drainer, test) lets
    every event module finish loading before we walk ``vars(m)``.
    """
    global _BOOTSTRAPPED  # noqa: PLW0603
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    _bootstrap_event_registry()


def _bootstrap_event_registry() -> None:
    """Import every module that declares DomainEvent subclasses so they
    self-register. Adding a new event? Add its module here. CI test
    ``test_event_registry_covers_all_subclasses`` enforces this.
    """
    # Local imports keep startup graph explicit and avoid circulars at
    # module-import time.
    modules = (
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
    import importlib

    for mod in modules:
        try:
            m = importlib.import_module(mod)
        except ImportError:
            # Bootstrap MUST not crash app/worker startup. The covering
            # test ``test_event_registry_covers_all_known_*`` asserts
            # completeness in CI. Only ImportError is expected here —
            # any other exception (SyntaxError, RuntimeError raised at
            # module top-level) propagates so we don't silently boot
            # with a broken event registry.
            continue
        for attr in vars(m).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, DomainEvent)
                and attr is not DomainEvent
                and attr.__module__ == m.__name__
            ):
                try:
                    register_event(attr)
                except RuntimeError:
                    # collision already reported on first registration
                    pass


# --------------------------------------------------------------------------- #
# Request-scoped deferred queue                                                #
# --------------------------------------------------------------------------- #

_deferred_queue: ContextVar[list[DomainEvent] | None] = ContextVar(
    "nova_deferred_event_queue", default=None
)


def begin_request_scope() -> Token[list[DomainEvent] | None]:
    """Open a deferred-publish scope. All subsequent ``bus.publish`` calls
    in this async context queue into a request-local list until either
    ``flush_request_scope`` (post-commit) or ``discard_request_scope``
    (rollback) is invoked.

    Returns the ContextVar token so the caller can restore the previous
    scope when this one ends (supports nested scopes, though we expect
    flat usage from FastAPI dependencies).
    """
    return _deferred_queue.set([])


def is_request_scope_active() -> bool:
    return _deferred_queue.get() is not None


def discard_request_scope(token: Token[list[DomainEvent] | None]) -> None:
    """Drop all queued events without dispatching (rollback path)."""
    try:
        _deferred_queue.reset(token)
    except (ValueError, LookupError):
        # Token may have already been reset by a nested scope or by the
        # event-loop teardown — safe to ignore.
        pass


async def flush_request_scope(
    bus: EventBus, token: Token[list[DomainEvent] | None]
) -> None:
    """Dispatch all queued events through ``bus`` immediately, then close
    the scope. Called by ``get_session`` / ``session_scope`` AFTER
    ``await session.commit()`` so handlers see committed data.

    Failure isolation (ADR-0030):
      - Per-handler try/except: sibling handlers run even if one raises.
      - Failed handler invocations are spooled to the ``outbox`` table.
      - **F1**: if the spool itself raises, log + swallow. We never
        propagate a post-commit handler failure into the user response.
      - **F3**: if a handler raises after publishing cascade events into
        the same scope, those cascade events are truncated and never
        dispatch — a failed upstream event must not produce downstream
        side-effects.
    """
    from app.core.logging import get_logger

    log = get_logger("event_bus.flush")
    queue = _deferred_queue.get() or []
    try:
        # Index-driven walk so cascade events appended by handlers are
        # observed and processed (or truncated on failure).
        i = 0
        while i < len(queue):
            event = queue[i]
            for handler in bus._handlers.get(type(event), []):  # noqa: SLF001
                len_before = len(queue)
                try:
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:  # noqa: BLE001
                    # F3: truncate cascade events this handler enqueued
                    # before raising. They lose their causal trigger
                    # and must not dispatch.
                    if len(queue) > len_before:
                        del queue[len_before:]
                    try:
                        await _spool_to_outbox(event, exc)
                    except Exception:  # noqa: BLE001
                        # F1: last-resort log; NEVER propagate out of
                        # flush. The publisher's commit already
                        # succeeded — a downstream failure must not
                        # 500 the user.
                        log.critical(
                            "event_bus.spool_unrecoverable",
                            event_type=type(event).__name__,
                        )
            i += 1
    finally:
        try:
            _deferred_queue.reset(token)
        except (ValueError, LookupError):
            pass


# --------------------------------------------------------------------------- #
# Outbox spool — best-effort dead-letter for post-commit handler failures.    #
# Replay happens in worker/outbox_drainer.py via EVENT_REGISTRY.              #
# --------------------------------------------------------------------------- #


def event_payload(event: DomainEvent) -> dict[str, Any]:
    """JSON-serialisable view of an event for the ``outbox`` table.

    Replayability contract: ``EVENT_REGISTRY[event_type](**payload)``
    must reconstruct an event equivalent to the original. Decimal,
    UUID, datetime are coerced to JSON-safe primitives; the registry
    class' ``__post_init__`` (or domain constructor) is responsible for
    coercing them back to typed values on replay.
    """
    if not is_dataclass(event):
        return {"repr": repr(event)}

    def _coerce(v: Any) -> Any:
        if v is None or isinstance(v, (str, int, bool)):
            return v
        if isinstance(v, float):
            return v
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, (list, tuple)):
            return [_coerce(x) for x in v]
        if isinstance(v, dict):
            return {str(k): _coerce(x) for k, x in v.items()}
        return repr(v)

    return {f.name: _coerce(getattr(event, f.name)) for f in fields(event)}


# Backwards-compat alias (some tests imported the private name).
_event_payload = event_payload


def _event_aggregate(event: DomainEvent) -> tuple[str, str | None]:
    """Best-effort aggregate identification for outbox indexing.

    Returns ``(canonical_event_type, user_id_or_None)``. ``aggregate``
    column is kept human-readable (short class name) while
    ``event_type`` carries the module-qualified canonical name so the
    drainer can dispatch via ``EVENT_REGISTRY``.
    """
    short_name = type(event).__name__
    user_id = getattr(event, "user_id", None)
    if isinstance(user_id, UUID):
        return short_name, str(user_id)
    if isinstance(user_id, str):
        return short_name, user_id
    return short_name, None


async def _spool_to_outbox(event: DomainEvent, exc: BaseException) -> None:
    """Persist a failed post-commit handler dispatch to ``outbox`` so the
    drainer worker can replay it asynchronously.

    Best-effort: if this function raises, the caller in
    ``flush_request_scope`` will log ``event_bus.spool_unrecoverable``
    and continue — we never propagate handler failure back to the user
    request that already succeeded (F1).
    """
    from app.core.logging import get_logger

    log = get_logger("event_bus.outbox")
    short_name, aggregate_id = _event_aggregate(event)
    canonical_type = event_type_name(type(event))
    try:
        from sqlalchemy import text

        from app.core.db import session_scope

        async with session_scope() as s:
            await s.execute(
                text(
                    """
                    INSERT INTO outbox
                        (aggregate, aggregate_id, event_type, payload,
                         attempts, last_error)
                    VALUES (:agg, :agg_id, :etype, CAST(:payload AS jsonb),
                            0, :err)
                    """
                ),
                {
                    "agg": short_name,
                    # aggregate_id NOT NULL in schema 0009 — fall back to
                    # all-zero UUID when the event has no user_id (system
                    # events). Drainer treats this as "no aggregate".
                    "agg_id": aggregate_id or "00000000-0000-0000-0000-000000000000",
                    "etype": canonical_type,
                    "payload": json.dumps(event_payload(event)),
                    "err": f"{type(exc).__name__}: {exc}",
                },
            )
        log.warning(
            "event_bus.handler_failed_spooled",
            event=canonical_type,
            aggregate_id=aggregate_id,
            error=str(exc),
        )
    except Exception as spool_exc:  # noqa: BLE001
        # Log AND re-raise so flush_request_scope can convert this into
        # the "spool_unrecoverable" final-log path (F1). Without the
        # re-raise the flush loop could not distinguish "spool worked"
        # from "spool failed but we logged" — and tests cannot assert
        # the unrecoverable code path.
        log.error(
            "event_bus.outbox_spool_failed",
            event=canonical_type,
            aggregate_id=aggregate_id,
            handler_error=str(exc),
            spool_error=str(spool_exc),
        )
        raise


# --------------------------------------------------------------------------- #
# EventBus                                                                     #
# --------------------------------------------------------------------------- #


class EventBus:
    """Domain event bus with deferred-dispatch semantics.

    - When a request scope is active (``is_request_scope_active`` returns
      True), ``publish`` enqueues. Dispatch happens on
      ``flush_request_scope`` after the session commits.
    - Otherwise (unit tests, worker code outside requests), dispatch is
      immediate — preserves backwards compatibility with direct
      ``EventBus()`` instantiation.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        queue = _deferred_queue.get()
        if queue is not None:
            queue.append(event)
            return
        await self._dispatch(event)

    async def publish_many(self, events: list[DomainEvent]) -> None:
        queue = _deferred_queue.get()
        if queue is not None:
            queue.extend(events)
            return
        # Immediate mode preserves the original gather semantics AND
        # routes through ``self.publish`` so subclasses that override
        # ``publish`` (test spies) still observe every event.
        await asyncio.gather(*(self.publish(e) for e in events))

    async def _dispatch(self, event: DomainEvent) -> None:
        """Invoke every handler registered for ``type(event)``.

        Handlers run sequentially (no gather) so that ordering between
        handlers of the same event type is deterministic. This matches
        the behaviour the original immediate-mode bus exhibited inside
        ``publish``.
        """
        for handler in self._handlers.get(type(event), []):
            result = handler(event)
            if inspect.isawaitable(result):
                await result

    async def dispatch_immediate(self, event: DomainEvent) -> None:
        """Dispatch an event RIGHT NOW, bypassing any active request
        scope. Used by the outbox drainer to replay events without
        re-queuing them into the drainer's own session scope.
        """
        await self._dispatch(event)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus  # noqa: PLW0603 — lazy module-level singleton, intentional
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus_for_tests() -> None:
    """Clear the module-level singleton — test fixtures only."""
    global _bus  # noqa: PLW0603
    _bus = None


# Registry bootstrap deferred until first consumer (drainer / test) —
# see ``ensure_event_registry_bootstrapped`` for the rationale.
