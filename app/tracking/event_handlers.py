"""Tracking event handlers — invalidate per-day totals cache on writes."""

from __future__ import annotations

from datetime import date

from app.core.event_bus import EventBus
from app.core.redis import get_redis
from app.tracking.application.food_log_uc import _cache_key_totals
from app.tracking.domain.events import FoodLogged


def register(bus: EventBus) -> None:
    async def _on_food_logged(evt: FoodLogged) -> None:
        try:
            await get_redis().delete(_cache_key_totals(evt.user_id, date.today()))
        except Exception:  # noqa: BLE001 — cache miss is acceptable
            pass

    bus.subscribe(FoodLogged, _on_food_logged)
