"""Local error tracker for MVP phase.

Captures unhandled exceptions in API + workers without sending data to any
third-party service. Three storage layers:

1. **structlog JSON** (already configured) → stdout → Dokploy container logs.
2. **Rotated file** at `nova_error_log_path` (default /var/log/nova/errors.jsonl).
   30-day rotation, jsonl format greppable from shell.
3. **In-memory ring buffer** (last 500 errors) exposed via admin endpoint
   `GET /admin/errors/recent` for quick self-inspection without SSH.

Prometheus counter `nova_unhandled_errors_total{type}` increments per
exception class. Alert if rate >5/min indicates regression.

Zero external dependency. Zero monthly cost. RAM cost ≈ 500 * ~2KB = 1MB.
"""

from __future__ import annotations

import json
import os
import threading
import traceback
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import Counter
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

log = get_logger("error_tracker")

UNHANDLED_ERRORS = Counter(
    "nova_unhandled_errors_total",
    "Unhandled exceptions captured by ErrorTracker",
    ["type", "endpoint_class"],
)

_RING_MAX = 500
_ring: deque[dict[str, Any]] = deque(maxlen=_RING_MAX)
_ring_lock = threading.Lock()


def _safe_endpoint_class(path: str) -> str:
    """Coarse-grain endpoint label to avoid Prometheus cardinality explosion.
    e.g. /v1/plans/{id} → 'plans'."""
    parts = [p for p in path.split("/") if p and not p.startswith("v")]
    if not parts:
        return "unknown"
    return parts[0][:32]


def record_error(
    *,
    exc: BaseException,
    path: str = "",
    user_id: str | None = None,
    request_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist error to ring buffer + file + metrics. Best-effort, never raises."""
    try:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "type": type(exc).__name__,
            "message": str(exc)[:500],
            "path": path,
            "user_id": user_id,
            "request_id": request_id,
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
            "extra": extra or {},
        }
        with _ring_lock:
            _ring.append(entry)
        UNHANDLED_ERRORS.labels(
            type=type(exc).__name__,
            endpoint_class=_safe_endpoint_class(path),
        ).inc()
        log.error("unhandled_exception", **{k: v for k, v in entry.items() if k != "traceback"})
        _append_to_file(entry)
    except Exception:  # noqa: BLE001,S110 — tracker must never raise
        pass


def _append_to_file(entry: dict) -> None:
    path = os.getenv("NOVA_ERROR_LOG_PATH", "/var/log/nova/errors.jsonl")
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001,S110 — file errors swallowed
        pass


def recent_errors(limit: int = 100) -> list[dict]:
    """Returns the most recent up-to-`limit` error entries (newest first)."""
    with _ring_lock:
        return list(reversed(list(_ring)))[:limit]


def clear_ring() -> int:
    with _ring_lock:
        n = len(_ring)
        _ring.clear()
        return n


class ErrorTrackerMiddleware(BaseHTTPMiddleware):
    """Catches unhandled exceptions, records them, re-raises so FastAPI's
    exception handlers can map them to JSON responses."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            user_id = None
            try:
                user_id = getattr(request.state, "user_id", None)
                if user_id is not None:
                    user_id = str(user_id)
            except Exception:  # noqa: BLE001,S110 — best-effort state read
                pass
            request_id = None
            try:
                request_id = getattr(request.state, "request_id", None)
            except Exception:  # noqa: BLE001,S110 — best-effort state read
                pass
            record_error(
                exc=exc,
                path=request.url.path,
                user_id=user_id,
                request_id=request_id,
            )
            raise
