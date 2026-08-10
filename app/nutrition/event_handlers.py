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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _five_kg_trigger(session: AsyncSession, user_id: UUID, current_weight_kg: Decimal) -> bool:
    """True if weight has changed ≥5 kg since the last goals calibration.

    PDF rule: "recalcular el plan cada 5 kg perdidos" — BMR is mass-dependent,
    so a 5 kg shift makes the current TDEE estimate meaningfully stale.
    Bypasses the 14-day cooldown when True (skip_cooldown=True).
    """
    row_goals = (
        await session.execute(
            text(
                "SELECT valid_from FROM nutritional_goals"
                " WHERE user_id = :uid AND valid_to IS NULL LIMIT 1"
            ),
            {"uid": str(user_id)},
        )
    ).first()
    if not row_goals:
        return False

    calibration_time = row_goals[0]
    row_weight = (
        await session.execute(
            text(
                """
        SELECT weight_kg FROM weight_logs
         WHERE user_id = :uid
         ORDER BY ABS(EXTRACT(EPOCH FROM (time - :cal_time::timestamptz)))
         LIMIT 1
        """
            ),
            {"uid": str(user_id), "cal_time": calibration_time},
        )
    ).first()
    if not row_weight:
        return False

    weight_at_calibration = Decimal(str(row_weight[0]))
    return abs(current_weight_kg - weight_at_calibration) >= Decimal("5")


@dataclass(frozen=True, slots=True)
class WeightLogged(DomainEvent):
    user_id: UUID
    weight_kg: Decimal
    at: datetime


async def _on_biometrics_changed(evt: BiometricsChanged) -> None:
    """Defensive baseline filler.

    Production baseline creation has moved INSIDE the originating
    transaction via `app.nutrition.infrastructure.compute_goals_adapter
    .InlineComputeGoals` (wired into `CompleteOnboarding` and
    `UpdateProfile`). That path eliminates the cross-session race that
    used to silently log `profile_not_found` and leave
    `nutritional_goals` empty (which then caused `POST /plans` to emit
    empty plan_meals).

    The handler is kept as a SAFETY NET that only fires when goals are
    still missing (e.g. an external publisher emits `BiometricsChanged`
    without using the inline path). Skips when a current row already
    exists so we never burn a recalibration slot.
    """
    if not (
        evt.weight_kg and evt.height_cm and evt.age and evt.sex and evt.goal and evt.activity_level
    ):
        return  # need full biometrics to compute baseline
    async with session_scope() as s:
        goals_repo = SqlNutritionalGoalsRepository(s)
        existing = await goals_repo.get_current(evt.user_id)
        if existing is not None:
            return  # primary inline path already produced the baseline
        uc = ComputeInitialGoals(
            profile_reader=SqlProfileReader(s),
            goals_repo=goals_repo,
            bus=__import__("app.core.event_bus", fromlist=["get_event_bus"]).get_event_bus(),
        )
        try:
            await uc(user_id=evt.user_id)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "nutrition.biometrics_baseline_failed", user_id=str(evt.user_id), error=str(e)
            )


async def _on_weight_logged(evt: WeightLogged) -> None:
    async with session_scope() as s:
        # T-10: bypass 14-day cooldown when weight delta since last calibration ≥ 5 kg
        skip_cool = await _five_kg_trigger(s, evt.user_id, evt.weight_kg)
        if skip_cool:
            log.info("nutrition.recalibrate.five_kg_trigger", user_id=str(evt.user_id))

        uc = RecalibrateGoals(
            profile_reader=SqlProfileReader(s),
            tracking_reader=SqlTrackingReader(s),
            goals_repo=SqlNutritionalGoalsRepository(s),
            bus=__import__("app.core.event_bus", fromlist=["get_event_bus"]).get_event_bus(),
        )
        result = await uc(user_id=evt.user_id, skip_cooldown=skip_cool)
        log.info(
            "nutrition.recalibrate.attempted",
            user_id=str(evt.user_id),
            result=type(result).__name__,
        )

        # T-12: coach nudge when user is measurably behind their weight plan
        try:
            from app.coach.application.features import weight_behind_alert
            sent = await weight_behind_alert(s, user_id=evt.user_id)
            if sent:
                log.info("nutrition.coach.weight_behind_alert.sent", user_id=str(evt.user_id))
        except Exception as exc:  # noqa: BLE001
            log.warning("nutrition.coach.weight_behind_alert.failed", error=str(exc))


def register(bus: EventBus) -> None:
    bus.subscribe(BiometricsChanged, _on_biometrics_changed)
    bus.subscribe(WeightLogged, _on_weight_logged)
    # Sprint 3.C — tracking context now owns the canonical WeightLogged.
    # EventBus.subscribe is keyed by class identity so we subscribe to both
    # until the duck-typed local copy can be retired.
    try:
        from app.tracking.domain.events import WeightLogged as TrackingWeightLogged

        bus.subscribe(TrackingWeightLogged, _on_weight_logged)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001,S110 — optional duck-typed subscription
        pass
