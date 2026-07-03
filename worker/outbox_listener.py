"""PostgreSQL LISTEN/NOTIFY outbox drainer.

Replaces the every-minute cron with zero-latency event-driven dispatch:
- DB trigger `trg_outbox_notify` fires `pg_notify('outbox_new_event', id)`
  on every INSERT into the outbox table.
- This module opens a raw asyncpg connection (not SQLAlchemy) and
  listens on that channel.
- On notification, calls `drain_outbox_once()` which picks up all ready
  rows (SKIP LOCKED) and replays them through the in-process EventBus.

Reconnect: if the connection drops (network blip, DB restart) the loop
catches the exception, waits 5s, and reconnects. No manual intervention
needed.

No polling. No RAM overhead. No VPS load between events.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import asyncpg

from app.core.config import get_settings
from app.core.logging import get_logger
from worker.outbox_drainer import drain_outbox_once

log = get_logger("worker.outbox_listener")

_RECONNECT_DELAY_S = 5
_CHANNEL = "outbox_new_event"


def _asyncpg_dsn(database_url: str) -> str:
    # SQLAlchemy uses postgresql+asyncpg://... — asyncpg wants postgresql://...
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


async def _listen_loop(dsn: str) -> None:
    while True:
        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(dsn)

            async def _on_notification(
                _conn: asyncpg.Connection,
                _pid: int,
                _channel: str,
                _payload: str,
            ) -> None:
                try:
                    result = await drain_outbox_once()
                    if result["processed"] > 0:
                        log.info("outbox.listener.drained", **result)
                except Exception as exc:  # noqa: BLE001
                    log.warning("outbox.listener.drain_error", err=str(exc)[:200])

            await conn.add_listener(_CHANNEL, _on_notification)
            log.info("outbox.listener.connected", channel=_CHANNEL)

            # Keepalive — sleep forever until connection drops or process exits
            while True:
                await asyncio.sleep(60)
                # Heartbeat: drain any rows that arrived before we connected
                # (race window at startup) or whose notifications were lost.
                try:
                    result = await drain_outbox_once()
                    if result["processed"] > 0:
                        log.info("outbox.listener.heartbeat_drain", **result)
                except Exception as exc:  # noqa: BLE001
                    log.warning("outbox.listener.heartbeat_error", err=str(exc)[:200])

        except asyncio.CancelledError:
            if conn and not conn.is_closed():
                await conn.close()
            return
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "outbox.listener.reconnecting",
                err=str(exc)[:200],
                delay_s=_RECONNECT_DELAY_S,
            )
            if conn and not conn.is_closed():
                try:
                    await conn.close()
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(_RECONNECT_DELAY_S)


async def start_outbox_listener(ctx: dict[str, Any]) -> None:
    """Called from worker on_startup — spawns the listener as a background task."""
    dsn = _asyncpg_dsn(get_settings().database_url)
    task = asyncio.create_task(_listen_loop(dsn), name="outbox_listener")
    ctx["outbox_listener_task"] = task
    log.info("outbox.listener.started")


async def stop_outbox_listener(ctx: dict[str, Any]) -> None:
    """Called from worker on_shutdown — cancels the listener task cleanly."""
    task: asyncio.Task | None = ctx.get("outbox_listener_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    log.info("outbox.listener.stopped")
