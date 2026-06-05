"""Nutrition use cases.

Two flows:
  1) compute_initial_goals — invoked on onboarding (or first valid biometrics)
  2) recalibrate_goals — event handler for WeightLogged (subscribed in event bus)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.nutrition.domain.errors import BmrSafetyFloorViolated
from app.nutrition.domain.hydration import compute_water_ml
from app.nutrition.domain.kcal_range import to_range
from app.nutrition.domain.macro_partitioning import compute_macros
from app.nutrition.domain.mifflin_st_jeor import compute_bmr
from app.nutrition.domain.recalibration import (
    COOLDOWN_DAYS,
    RecalibrationInput,
    RecalibrationResult,
    RecalibrationSkipped,
    recalibrate,
)
from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.domain.tdee import compute_tdee
from app.plan.domain.bmr_safety import (
    KcalTargetBelowSafetyFloor,
    apply_lactation_adjustment,
    apply_trimester_adjustment,
    enforce_bmr_safety_floor,
)

_log = get_logger("nutrition.use_cases")


def _bmr_safety_warn(*, user_id: UUID, kcal_target: int, bmr: int) -> None:
    """Warn (do not raise) when kcal_target below BMR safety floor.

    Master plan H1.4 invariant: kcal_target >= bmr * 0.9. Existing flow
    currently clamps at 800 kcal which can sit below this floor for small
    female users under weight_loss. Warn for telemetry; do not break
    onboarding. Future migration to Decimal-strict path will enforce.
    """
    floor = int(round(bmr * 0.9))
    if kcal_target < floor:
        _log.warning(
            "kcal_target_below_bmr_safety_floor",
            user_id=str(user_id),
            kcal_target=kcal_target,
            bmr=bmr,
            floor=floor,
        )


def _now() -> datetime:
    return datetime.now(tz=UTC)


_GOAL_KCAL_DELTA = {
    "weight_loss": -500,
    "maintain": 0,
    "muscle_gain": +300,
    "weight_gain": +500,
    "health": 0,
}

_ACTIVITY_FACTOR = {
    "sedentary": Decimal("1.20"),
    "lightly_active": Decimal("1.375"),
    "moderately_active": Decimal("1.55"),
    "very_active": Decimal("1.725"),
    "extra_active": Decimal("1.90"),
}


class NutritionalGoalsRepository(Protocol):
    async def get_current(self, user_id: UUID) -> NutritionalGoals | None: ...
    async def list_history(self, user_id: UUID, limit: int) -> list[NutritionalGoals]: ...
    async def expire_current_and_insert(
        self,
        user_id: UUID,
        new_goals: NutritionalGoals,
    ) -> NutritionalGoals: ...
    async def acquire_user_lock(self, user_id: UUID) -> None:
        """Acquire a per-user serialisation lock for the current transaction.

        Sprint 3 D5. Implementations should use a mechanism that scopes
        to the active transaction and releases on commit/rollback —
        on Postgres this is `pg_advisory_xact_lock`. The point of this
        lock is to serialise concurrent recalibrations for the same
        user without blocking other users; the partial unique index
        `one_current_goals` remains the last-line defence.
        """
        ...


class ProfileReader(Protocol):
    async def biometrics(self, user_id: UUID) -> dict | None: ...

    """Returns {weight_kg, height_cm, age, sex, goal, activity_level,
    conditions: frozenset[str], trimester: "first"|"second"|"third"|None}
    or None. `conditions` carries medical conditions used by R8 hydration
    caps (CKD/CHF) — empty frozenset when absent (never None). `trimester`
    drives the IOM DRI 2002 pregnancy kcal surplus; `None` when not
    pregnant or when the reader omits the key (backward compat)."""


class TrackingReader(Protocol):
    async def weight_series_14d(self, user_id: UUID) -> list[tuple[int, float]]: ...
    async def kcal_in_14d(self, user_id: UUID) -> list[int]: ...


def _adjust_and_enforce_floor(
    *,
    user_id: UUID,
    kcal_target_int: int,
    bmr_int: int,
    conditions: frozenset[str],
    trimester: str | None,
) -> int:
    """Apply lactation + pregnancy surpluses, then enforce BMR safety floor.

    Order is intentional:
      1. Lactation +500 (IOM DRI breastfeeding).
      2. Trimester +0/+340/+452 (IOM DRI 2002 pregnancy).
      3. BMR * 0.9 floor (AND/ACSM/Dietitians of Canada 2016, RED-S risk).

    Surpluses are applied BEFORE the floor check so the floor evaluates
    the FINAL kcal_target (a lactating user with a small frame is no
    longer in an unsafe regime once +500 is included).

    Raises `BmrSafetyFloorViolated` (DomainError, 422) when the final
    target still lands below the floor — the warn helper remains as
    defense-in-depth telemetry but no longer decides the outcome.
    """
    target = Decimal(kcal_target_int)
    target = apply_lactation_adjustment(kcal_target=target, conditions=conditions)
    target = apply_trimester_adjustment(
        kcal_target=target,
        trimester=trimester,  # type: ignore[arg-type]
    )
    bmr_d = Decimal(bmr_int)
    try:
        enforce_bmr_safety_floor(kcal_target=target, bmr=bmr_d)
    except KcalTargetBelowSafetyFloor as exc:
        # Surface as a DomainError so the RFC 7807 translator emits a 422
        # with `kcal_target` + `floor` in the problem+json `extra` block.
        raise BmrSafetyFloorViolated(
            kcal_target=exc.target,
            floor=exc.floor,
        ) from exc
    return int(target)


def _build_goals(
    *,
    user_id: UUID,
    sex: str,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
    goal: str,
    activity_level: str,
    reason: str,
    conditions: frozenset[str] = frozenset(),
    trimester: str | None = None,
) -> NutritionalGoals:
    af = _ACTIVITY_FACTOR[activity_level]
    bmr = compute_bmr(sex=sex, weight_kg=weight_kg, height_cm=height_cm, age=age)  # type: ignore[arg-type]
    tdee_base = compute_tdee(bmr, af)
    kcal_target = max(800, tdee_base + _GOAL_KCAL_DELTA.get(goal, 0))
    # Apply lactation + pregnancy surpluses, then enforce BMR safety floor.
    # Order matters — see `_adjust_and_enforce_floor` docstring.
    kcal_target = _adjust_and_enforce_floor(
        user_id=user_id,
        kcal_target_int=kcal_target,
        bmr_int=bmr,
        conditions=conditions,
        trimester=trimester,
    )
    _bmr_safety_warn(user_id=user_id, kcal_target=kcal_target, bmr=bmr)
    macros = compute_macros(kcal_target=kcal_target, weight_kg=weight_kg, goal=goal)  # type: ignore[arg-type]
    krange = to_range(kcal_target)
    # D1 — feed `conditions` so CKD/CHF caps activate (defense-in-depth).
    water = compute_water_ml(
        weight_kg=weight_kg,
        activity_factor=af,
        conditions=conditions,
    )
    return NutritionalGoals.new(
        user_id=user_id,
        kcal_min=krange.min,
        kcal_max=krange.max,
        protein_g=macros.protein_g,
        carbs_g=macros.carbs_g,
        fat_g=macros.fat_g,
        water_ml=water,
        bmr=bmr,
        tdee=tdee_base,
        activity_factor=af,
        reason=reason,  # type: ignore[arg-type]
        valid_from=_now(),
    )


@dataclass(slots=True)
class ComputeInitialGoals:
    profile_reader: ProfileReader
    goals_repo: NutritionalGoalsRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> NutritionalGoals:
        bio = await self.profile_reader.biometrics(user_id)
        if not bio:
            raise NotFoundError("profile_not_found")
        for k in ("weight_kg", "height_cm", "age", "sex", "goal", "activity_level"):
            if bio.get(k) is None:
                raise BusinessRuleViolation(f"profile_missing:{k}")
        goals = _build_goals(
            user_id=user_id,
            sex=bio["sex"],
            weight_kg=bio["weight_kg"],
            height_cm=bio["height_cm"],
            age=bio["age"],
            goal=bio["goal"],
            activity_level=bio["activity_level"],
            reason="onboarding",
            conditions=frozenset(bio.get("conditions") or ()),
            trimester=bio.get("trimester"),
        )
        return await self.goals_repo.expire_current_and_insert(user_id, goals)


@dataclass(slots=True)
class RecalibrateGoals:
    profile_reader: ProfileReader
    tracking_reader: TrackingReader
    goals_repo: NutritionalGoalsRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> RecalibrationResult | RecalibrationSkipped:
        # Cooldown PRE-FLIGHT (Sprint 3 race fix) — read current goals first
        # to compute cooldown WITHOUT acquiring the advisory lock. If we're
        # inside the 14-day cooldown the recalibration is a guaranteed skip,
        # so taking pg_advisory_xact_lock would only contend with concurrent
        # callers and (historically) deadlocked the integration suite. The
        # algorithm-level cooldown check inside `recalibrate()` remains as
        # defence in depth.
        current = await self.goals_repo.get_current(user_id)
        if current is None:
            return RecalibrationSkipped("no_baseline")
        days_since = max(0, (_now() - current.valid_from).days)
        if days_since < COOLDOWN_DAYS:
            return RecalibrationSkipped("cooldown")

        # Sprint 3 D5 — Serialise concurrent recalibrations per user via
        # pg_advisory_xact_lock so the read-then-write below is race-free.
        # The partial unique index `one_current_goals` remains the storage
        # invariant; if the advisory lock is bypassed (e.g. different DB
        # session not holding the lock), the IntegrityError catch at the
        # bottom of this method downgrades the conflict into a clean skip.
        await self.goals_repo.acquire_user_lock(user_id)

        bio = await self.profile_reader.biometrics(user_id)
        # Re-read current after acquiring the lock — a concurrent writer may
        # have advanced valid_from between the pre-flight read and the lock.
        current = await self.goals_repo.get_current(user_id)
        if not bio or not current:
            return RecalibrationSkipped("no_baseline")
        days_since = max(0, (_now() - current.valid_from).days)
        weights = await self.tracking_reader.weight_series_14d(user_id)
        kcal_in = await self.tracking_reader.kcal_in_14d(user_id)

        result = recalibrate(
            RecalibrationInput(
                sex=bio["sex"],
                weight_kg_now=bio["weight_kg"],
                height_cm=bio["height_cm"],
                age=bio["age"],
                activity_factor=current.activity_factor,
                goal=bio["goal"],
                tdee_current=current.tdee,
                days_since_last_recalibration=days_since,
                weights=weights,
                kcal_in=kcal_in,
            )
        )
        if isinstance(result, RecalibrationSkipped):
            return result

        # Rebuild full goals row using the new TDEE (rederive macros + water).
        af = current.activity_factor
        # We back into kcal_target from new TDEE + goal delta.
        kcal_target = max(800, result.tdee_new + _GOAL_KCAL_DELTA.get(bio["goal"], 0))
        # H1.4 — apply lactation/pregnancy surpluses + enforce BMR safety
        # floor on the FINAL target. Same precedence as `_build_goals`.
        kcal_target = _adjust_and_enforce_floor(
            user_id=user_id,
            kcal_target_int=kcal_target,
            bmr_int=result.bmr_new,
            conditions=frozenset(bio.get("conditions") or ()),
            trimester=bio.get("trimester"),
        )
        macros = compute_macros(
            kcal_target=kcal_target, weight_kg=bio["weight_kg"], goal=bio["goal"]
        )
        krange = to_range(kcal_target)
        # D1 — conditions threaded so CKD/CHF still cap fluids post-recalibration.
        water = compute_water_ml(
            weight_kg=bio["weight_kg"],
            activity_factor=af,
            conditions=frozenset(bio.get("conditions") or ()),
        )

        new_goals = NutritionalGoals.new(
            user_id=user_id,
            kcal_min=krange.min,
            kcal_max=krange.max,
            protein_g=macros.protein_g,
            carbs_g=macros.carbs_g,
            fat_g=macros.fat_g,
            water_ml=water,
            bmr=result.bmr_new,
            tdee=result.tdee_new,
            activity_factor=af,
            reason=result.reason,
            valid_from=_now(),
        )
        try:
            await self.goals_repo.expire_current_and_insert(user_id, new_goals)
        except IntegrityError as exc:
            # Defence-in-depth: a concurrent recalibration won the race
            # despite the advisory lock (possible only if the other writer
            # ran on a session that did not acquire the lock). Postgres
            # partial unique index `one_current_goals` rejected the second
            # INSERT. Downgrade to a clean skip rather than propagating
            # a 500 — the data is consistent; the recalibration is simply
            # superseded by the winning writer.
            _log.warning(
                "recalibration_concurrent_conflict",
                user_id=str(user_id),
                error=str(exc.orig) if exc.orig else str(exc),
            )
            return RecalibrationSkipped("concurrent_recalibration")
        return result


@dataclass(slots=True)
class GetCurrentGoals:
    goals_repo: NutritionalGoalsRepository

    async def __call__(self, *, user_id: UUID) -> NutritionalGoals:
        g = await self.goals_repo.get_current(user_id)
        if g is None:
            raise NotFoundError("goals_not_found")
        return g


@dataclass(slots=True)
class GetGoalsHistory:
    goals_repo: NutritionalGoalsRepository

    async def __call__(self, *, user_id: UUID, limit: int = 20) -> list[NutritionalGoals]:
        return await self.goals_repo.list_history(user_id, limit)
