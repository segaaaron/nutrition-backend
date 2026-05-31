"""Bind nutrition recalibration to upstream domain events.

Currently subscribes to:
  - BiometricsChanged (profile)  → recalc baseline goals
  - WeightLogged       (tracking) → ADR-0002 recalibration loop

`WeightLogged` is declared inline here for now so the subscription wires up
even before the tracking bounded context lands. When the tracking context is
implemented (Sprint 3 onward) it should import this `WeightLogged` symbol or
re-export it from `app.tracking.domain.events`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.core.db import session_scope
from app.core.event_bus import DomainEvent, EventBus
from app.core.logging import get_logger
from app.nutrition.application.use_cases import (
    ComputeInitialGoals,
    RecalibrateGoals,
)
from app.nutrition.infrastructure.repositories import (
    SqlNutritionalGoalsRepository,
    SqlProfileReader,
    SqlTrackingReader,
)
from app.profile.domain.events import BiometricsChanged

log = get_logger("nutrition.handlers")


@dataclass(frozen=True, slots=True)
class WeightLogged(DomainEvent):
    user_id: UUID
    weight_kg: Decimal
    at: datetime


async def _on_biometrics_changed(evt: BiometricsChanged) -> None:
    if not (evt.weight_kg and evt.height_cm and evt.age and evt.sex
            and evt.goal and evt.activity_level):
        return  # need full biometrics to compute baseline
    async with session_scope() as s:
        uc = ComputeInitialGoals(
            profile_reader=SqlProfileReader(s),
            goals_repo=SqlNutritionalGoalsRepository(s),
            bus=__import__("app.core.event_bus", fromlist=["get_event_bus"]).get_event_bus(),
        )
        try:
            await uc(user_id=evt.user_id)
        except Exception as e:  # noqa: BLE001
            log.warning("nutrition.biometrics_baseline_failed", user_id=str(evt.user_id), error=str(e))


async def _on_weight_logged(evt: "WeightLogged") -> None:
    async with session_scope() as s:
        uc = RecalibrateGoals(
            profile_reader=SqlProfileReader(s),
            tracking_reader=SqlTrackingReader(s),
            goals_repo=SqlNutritionalGoalsRepository(s),
            bus=__import__("app.core.event_bus", fromlist=["get_event_bus"]).get_event_bus(),
        )
        result = await uc(user_id=evt.user_id)
        log.info("nutrition.recalibrate.attempted", user_id=str(evt.user_id), result=type(result).__name__)


def register(bus: EventBus) -> None:
    bus.subscribe(BiometricsChanged, _on_biometrics_changed)
    bus.subscribe(WeightLogged, _on_weight_logged)
