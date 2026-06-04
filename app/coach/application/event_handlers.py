"""Wire-up of coach reactions to vision events.

`FoodPhotoLogged` → `foto_cross_check` (Feature B).
Registered into the in-process event bus at app startup.
"""

from __future__ import annotations

from app.coach.application.features import foto_cross_check
from app.core.db import session_scope
from app.core.event_bus import EventBus
from app.vision.domain.events import FoodPhotoLogged


def register(bus: EventBus) -> None:
    async def _on_food_photo_logged(evt: FoodPhotoLogged) -> None:
        async with session_scope() as session:
            await foto_cross_check(
                session,
                user_id=evt.user_id,
                meal_time=evt.meal_time,
                detected_kcal=evt.kcal,
                detected_names=evt.detected_names,
            )

    bus.subscribe(FoodPhotoLogged, _on_food_photo_logged)
