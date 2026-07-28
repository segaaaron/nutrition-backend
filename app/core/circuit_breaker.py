"""Generic three-state circuit breaker for outbound dependencies.

Lifecycle:
  closed → (fail_threshold consecutive failures) → open
  open → (recovery_timeout_s elapsed) → half_open
  half_open → success → closed
  half_open → failure → open (reset clock)

Metrics: `circuit_breaker_state{name}` (gauge, 0=closed/1=half/2=open) and
`circuit_breaker_failures_total{name}` (counter). Both exposed on /metrics.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from prometheus_client import Counter, Gauge

from app.core.errors import UpstreamError

T = TypeVar("T")

_state_gauge = Gauge(
    "circuit_breaker_state",
    "Current state of a circuit breaker (0=closed,1=half_open,2=open)",
    ["name"],
)
_failures_counter = Counter(
    "circuit_breaker_failures_total",
    "Total recorded failures per circuit breaker",
    ["name"],
)
_opens_counter = Counter(
    "circuit_breaker_opens_total",
    "Total times a breaker transitioned to OPEN",
    ["name"],
)


class CircuitBreakerOpen(UpstreamError):
    type_slug = "circuit-open"
    title = "Upstream temporarily unavailable"


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str,
        fail_threshold: int = 3,
        recovery_timeout_s: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.fail_threshold = fail_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.half_open_max_calls = half_open_max_calls

        self._state: str = "closed"  # closed | open | half_open
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_inflight = 0
        self._lock = asyncio.Lock()
        _state_gauge.labels(name=self.name).set(0)

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, new_state: str) -> None:
        self._state = new_state
        _state_gauge.labels(name=self.name).set({"closed": 0, "half_open": 1, "open": 2}[new_state])

    async def _try_transition_from_open(self) -> None:
        if self._state != "open":
            return
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at >= self.recovery_timeout_s:
            self._set_state("half_open")
            self._half_open_inflight = 0

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            await self._try_transition_from_open()
            if self._state == "open":
                raise CircuitBreakerOpen(f"breaker_open:{self.name}")
            if self._state == "half_open" and self._half_open_inflight >= self.half_open_max_calls:
                raise CircuitBreakerOpen(f"breaker_half_open_saturated:{self.name}")
            if self._state == "half_open":
                self._half_open_inflight += 1

        try:
            result = await fn()
        except Exception:  # noqa: BLE001 — OK6: wraps arbitrary caller-supplied coroutine; type unknown at design time
            async with self._lock:
                self._failures += 1
                _failures_counter.labels(name=self.name).inc()
                if self._state == "half_open":
                    self._set_state("open")
                    self._opened_at = time.monotonic()
                    _opens_counter.labels(name=self.name).inc()
                    self._half_open_inflight = 0
                elif self._failures >= self.fail_threshold:
                    self._set_state("open")
                    self._opened_at = time.monotonic()
                    _opens_counter.labels(name=self.name).inc()
            raise
        else:
            async with self._lock:
                self._failures = 0
                if self._state == "half_open":
                    self._set_state("closed")
                    self._half_open_inflight = 0
                    self._opened_at = None
            return result
