"""Outbox drainer — ADR-0030 §Replay Semantics.

Cron task that picks up rows from the ``outbox`` table written by
``app.core.event_bus._spool_to_outbox`` (post-commit handler failures)
and **actually replays them** by:

1. Reconstructing the original DomainEvent via ``EVENT_REGISTRY`` keyed
   on the canonical ``event_type`` column (module-qualified name).
2. Invoking ``bus.dispatch_immediate(event)`` which fans out to every
   subscribed handler. Bypasses the deferred queue — the drainer is
   already past commit by definition.
3. Updating ``outbox.dispatched_at = now()`` on success.

On failure:
- ``attempts += 1``, ``last_error = '<exc>'``,
- exponential backoff via ``next_retry_at = now() + 2^attempts seconds``,
  capped at 30 minutes (migration 0015).
- After ``MAX_ATTEMPTS=10`` consecutive failures the row is marked
  ``dispatched_at = now(), last_error = 'dead_letter:<...>'`` and left
  for ops inspection. Drainer never deletes rows — outbox doubles as
  audit log.

Row locking: ``SELECT ... FOR UPDATE SKIP LOCKED`` ensures concurrent
drainer instances do not double-dispatch.

Replay safety: handlers must be idempotent. The drainer does NOT
filter events by type; if a row exists in outbox with a registered
event_type, it WILL be replayed.

Schema drift: rows persisted before migration 0015 lack
``next_retry_at`` — Postgres returns NULL which we treat as "ready
now", matching pre-migration semantics. Rows persisted before
EVENT_REGISTRY was introduced may have a short event_type (e.g.
``"WeightLogged"``) that is not in the registry → handled as
``unknown_event_type`` → counts as a failed attempt and eventually
dead-letters.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.core.db import session_scope
from app.core.event_bus import (
    EVENT_REGISTRY,
    DomainEvent,
    ensure_event_registry_bootstrapped,
    get_event_bus,
)
from app.core.logging import get_logger

log = get_logger("worker.outbox_drainer")

_MAX_ATTEMPTS = 10
_BATCH_SIZE = 50
_BACKOFF_BASE_SECONDS = 2
_BACKOFF_CAP_SECONDS = 30 * 60  # 30 minutes


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff: 2, 4, 8, ..., capped at 30 minutes.

    ``attempts`` is the new attempt count (already incremented).
    """
    raw = _BACKOFF_BASE_SECONDS ** max(1, attempts)
    return min(raw, _BACKOFF_CAP_SECONDS)


def _reconstruct(event_type: str, payload: dict[str, Any]) -> DomainEvent | None:
    """Best-effort reconstruction via ``EVENT_REGISTRY``.

    Returns ``None`` if the event_type is unknown (legacy row or
    deleted event class). On payload-shape mismatch the dataclass
    constructor raises ``TypeError`` and we propagate so the caller
    counts a failed attempt.
    """
    ensure_event_registry_bootstrapped()
    cls = EVENT_REGISTRY.get(event_type)
    if cls is None:
        return None
    # Dataclass constructors accept positional+keyword. Payloads stored
    # via ``event_payload`` use field names → kwargs work.
    return cls(**payload)


async def _replay(event_type: str, payload: dict[str, Any]) -> None:
    """Reconstruct the event and dispatch through the in-process bus.

    Raises on any failure so the caller bumps ``attempts``.
    """
    event = _reconstruct(event_type, payload)
    if event is None:
        raise LookupError(f"unknown_event_type:{event_type}")
    bus = get_event_bus()
    await bus.dispatch_immediate(event)


async def drain_outbox_once() -> dict[str, int]:
    """Process up to ``_BATCH_SIZE`` ready outbox rows.

    Returns ``{processed, replayed, failed, terminal, batch}`` for
    observability.

    Concurrency-safe: ``FOR UPDATE SKIP LOCKED`` guarantees that
    parallel drainer instances do not double-process rows.

    A single transaction wraps:
      - the SELECT FOR UPDATE
      - per-row replay
      - per-row UPDATE bookkeeping (success / failure / terminal)
    so row locks are released atomically when the session commits.
    """
    replayed = 0
    failed = 0
    terminal = 0
    rows: list[Any] = []

    async with session_scope() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT id, aggregate, aggregate_id, event_type,
                           payload, attempts, last_error
                      FROM outbox
                     WHERE dispatched_at IS NULL
                       AND (next_retry_at IS NULL OR next_retry_at <= now())
                     ORDER BY next_retry_at NULLS FIRST, created_at
                     LIMIT :n
                     FOR UPDATE SKIP LOCKED
                    """
                ),
                {"n": _BATCH_SIZE},
            )
        ).all()

        for row in rows:
            row_id = int(row[0])
            event_type = str(row[3])
            payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
            attempts = int(row[5]) + 1

            try:
                await _replay(event_type, payload)
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                if attempts >= _MAX_ATTEMPTS:
                    await s.execute(
                        text(
                            """
                            UPDATE outbox
                               SET attempts = :a,
                                   dispatched_at = now(),
                                   last_error = :err
                             WHERE id = :id
                            """
                        ),
                        {
                            "a": attempts,
                            "err": f"dead_letter:{err}",
                            "id": row_id,
                        },
                    )
                    log.error(
                        "outbox.dead_letter",
                        outbox_id=row_id,
                        event_type=event_type,
                        attempts=attempts,
                        last_error=err,
                    )
                    terminal += 1
                else:
                    backoff = _backoff_seconds(attempts)
                    await s.execute(
                        text(
                            """
                            UPDATE outbox
                               SET attempts = :a,
                                   last_error = :err,
                                   next_retry_at = now()
                                     + (:backoff * interval '1 second')
                             WHERE id = :id
                            """
                        ),
                        {
                            "a": attempts,
                            "err": err,
                            "backoff": backoff,
                            "id": row_id,
                        },
                    )
                    log.warning(
                        "outbox.replay_failed",
                        outbox_id=row_id,
                        event_type=event_type,
                        attempts=attempts,
                        backoff_seconds=backoff,
                        last_error=err,
                    )
                    failed += 1
                continue

            # Success path — mark dispatched, keep audit row.
            await s.execute(
                text(
                    """
                    UPDATE outbox
                       SET dispatched_at = now(),
                           attempts = :a,
                           last_error = NULL,
                           next_retry_at = NULL
                     WHERE id = :id
                    """
                ),
                {"a": attempts, "id": row_id},
            )
            log.info(
                "outbox.replayed",
                outbox_id=row_id,
                event_type=event_type,
                attempts=attempts,
            )
            replayed += 1

    return {
        "processed": replayed + failed + terminal,
        "replayed": replayed,
        "failed": failed,
        "terminal": terminal,
        "batch": len(rows),
    }


async def outbox_drainer_cron(ctx: dict[str, Any]) -> dict[str, int]:  # noqa: ARG001
    """Arq cron entry point — runs every minute via worker registration."""
    result = await drain_outbox_once()
    log.info("outbox.drainer_tick", **result)
    return result
