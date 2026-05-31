"""In-process domain event dispatcher. Synchronous-by-default; async handlers
are awaited inline. Cross-process fan-out goes through Arq / Redis pubsub.
"""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[[Any], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Marker base. Subclass with frozen dataclasses."""


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers.get(type(event), []):
            result = handler(event)
            if inspect.isawaitable(result):
                await result

    async def publish_many(self, events: list[DomainEvent]) -> None:
        await asyncio.gather(*(self.publish(e) for e in events))


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
