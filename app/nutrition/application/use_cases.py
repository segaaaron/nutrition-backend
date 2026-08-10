"""Nutrition use cases.

Two flows:
  1) compute_initial_goals — invoked on onboarding (or first valid biometrics)
  2) recalibrate_goals — event handler for WeightLogged (subscribed in event bus)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.nutrition.domain.errors import BmrSafetyFloorViolated
from app.nutrition.domain.ideal_weight import compute_bmi, compute_peterson_ideal
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
    apply_goal_to_tdee,
    apply_lactation_adjustment,
    apply_trimester_adjustment,
    enforce_bmr_safety_floor,
)
from app.plan.domain.water_calculator import calculate_water_target

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


_ACTIVITY_FACTOR = {
    "sedentary": Decimal("1.20"),
    "lightly_active": Decimal("1.375"),
    "moderately_active": Decimal("1.55"),
    "very_active": Decimal("1.725"),
    "extra_active": Decimal("1.90"),
}


class NutritionalGoalsRepository(Protocol):
    async def get_current(self, user_id: UUID) -> NutritionalGoals | None: ...
    async def list_history(self, user_id: UUID, limit: int, *, cursor: datetime | None = None) -> list[NutritionalGoals]: ...
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
    is_exclusively_breastfeeding: bool | None = None,
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
    target = apply_lactation_adjustment(
        kcal_target=target,
        conditions=conditions,
        is_exclusive=is_exclusively_breastfeeding,
    )
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


_DEFAULT_WEIGHT_KG_FALLBACK: Decimal = Decimal("70")
_BMI_OBESITY_THRESHOLD: Decimal = Decimal("30")


def _protein_weight(weight_kg: Decimal, height_cm: Decimal) -> Decimal:
    """Adjusted body weight for protein target when BMI ≥ 30.

    Using real weight overestimates protein needs in obesity because adipose
    tissue is metabolically less active than lean mass. The Hamwi/adjusted-BW
    formula (ADA Pocket Guide 2017) corrects this:
        PA = PI + 0.25 × (real − PI)
    where PI = Peterson (2016) ideal weight at BMI 22 (best validated point
    estimate on NHANES: Am J Clin Nutr 2016, doi:10.3945/ajcn.115.121178).

    Returns real weight unchanged when BMI < 30 — no adjustment needed.
    """
    w = weight_kg if isinstance(weight_kg, Decimal) else Decimal(str(weight_kg))
    h = height_cm if isinstance(height_cm, Decimal) else Decimal(str(height_cm))
    bmi = compute_bmi(weight_kg=w, height_cm=h)
    if bmi < _BMI_OBESITY_THRESHOLD:
        return w
    pi = compute_peterson_ideal(height_cm=h)
    return pi + Decimal("0.25") * (w - pi)


def _compute_water_target_ml(
    *,
    weight_kg: Decimal | None,
    kcal_daily: int,
    activity_level: str,
    goal: str,
    conditions: frozenset[str],
    region: str | None,
    pregnant: bool,
    lactating: bool,
) -> int:
    """Compute daily water target in ml via the NOVA hybrid algorithm.

    Single integration seam: nutrition use cases delegate to
    :func:`app.plan.domain.water_calculator.calculate_water_target` and persist
    only the resulting ``total_ml`` to ``nutritional_goals.water_ml`` —
    keeping the storage shape backward-compatible while upgrading the formula.

    Edge case: an absent ``weight_kg`` (should not happen in production because
    `_build_goals` validates it upstream, but `RecalibrateGoals` reads bio
    asynchronously and the row could be transiently empty) falls back to 70 kg
    with a warning rather than crashing the calibration run.
    """
    if weight_kg is None or weight_kg <= 0:
        _log.warning(
            "water_target_weight_kg_fallback",
            fallback_kg=str(_DEFAULT_WEIGHT_KG_FALLBACK),
        )
        weight_kg = _DEFAULT_WEIGHT_KG_FALLBACK
    target = calculate_water_target(
        weight_kg=weight_kg,
        kcal_daily=kcal_daily,
        activity=activity_level,
        region=region or "",
        month=_now().month,
        goal=goal,
        conditions=conditions,
        pregnant=pregnant,
        lactating=lactating,
    )
    return target.total_ml


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
    region: str | None = None,
    pregnant: bool = False,
    lactating: bool = False,
    is_exclusively_breastfeeding: bool | None = None,
) -> NutritionalGoals:
    af = _ACTIVITY_FACTOR[activity_level]
    bmr = compute_bmr(sex=sex, weight_kg=weight_kg, height_cm=height_cm, age=age)  # type: ignore[arg-type]
    tdee_base = compute_tdee(bmr, af)
    # Goal adjustment: weight_loss capped at min(500, 25% TDEE); muscle_gain
    # +250; weight_gain +300 (bmr_safety.apply_goal_to_tdee — sourced). The
    # 0.9*BMR floor below is the real safety guard (raises 422 if breached).
    kcal_target = int(apply_goal_to_tdee(tdee_val=Decimal(tdee_base), goal=goal))  # type: ignore[arg-type]
    # Apply lactation + pregnancy surpluses, then enforce BMR safety floor.
    # Order matters — see `_adjust_and_enforce_floor` docstring.
    kcal_target = _adjust_and_enforce_floor(
        user_id=user_id,
        kcal_target_int=kcal_target,
        bmr_int=bmr,
        conditions=conditions,
        trimester=trimester,
        is_exclusively_breastfeeding=is_exclusively_breastfeeding,
    )
    _bmr_safety_warn(user_id=user_id, kcal_target=kcal_target, bmr=bmr)
    # Protein calculation uses adjusted body weight when BMI ≥ 30.
    # Adipose tissue is metabolically inert; using real weight overestimates
    # protein by 30-50% in severe obesity, making the target unachievable with
    # real food. ADA Pocket Guide 2017 adjusted-BW formula via _protein_weight().
    pw = _protein_weight(weight_kg, height_cm)
    macros = compute_macros(kcal_target=kcal_target, weight_kg=pw, goal=goal)  # type: ignore[arg-type]
    krange = to_range(kcal_target)
    # NOVA hydration v2 — `calculate_water_target` honours kcal load, climate,
    # pregnancy / lactation, and the CKD/CHF medical override (≤1500 ml).
    water = _compute_water_target_ml(
        weight_kg=weight_kg,
        kcal_daily=kcal_target,
        activity_level=activity_level,
        goal=goal,
        conditions=conditions,
        region=region,
        pregnant=pregnant,
        lactating=lactating,
    )
    # Dietary targets for app progress bars (Dietary Guidelines 2020-2025 / WHO 2023).
    # weight_loss floor: 30g/day (IOM/Dietary Guidelines for satiety + metabolic benefit).
    fiber_target_g = max(1, int(round(kcal_target / 1000 * 14)))
    if goal == "weight_loss":
        fiber_target_g = max(fiber_target_g, 30)
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
        fiber_target_g=fiber_target_g,
        sodium_target_mg=2000,
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
            region=bio.get("region"),
            pregnant=bool(bio.get("pregnant")),
            lactating=bool(bio.get("lactating")),
            is_exclusively_breastfeeding=bio.get("is_exclusively_breastfeeding"),
        )
        return await self.goals_repo.expire_current_and_insert(user_id, goals)


@dataclass(slots=True)
class RecalibrateGoals:
    profile_reader: ProfileReader
    tracking_reader: TrackingReader
    goals_repo: NutritionalGoalsRepository
    bus: EventBus

    async def __call__(
        self, *, user_id: UUID, skip_cooldown: bool = False
    ) -> RecalibrationResult | RecalibrationSkipped:
        # Cooldown PRE-FLIGHT (Sprint 3 race fix) — read current goals first
        # to compute cooldown WITHOUT acquiring the advisory lock. If we're
        # inside the 14-day cooldown the recalibration is a guaranteed skip,
        # so taking pg_advisory_xact_lock would only contend with concurrent
        # callers and (historically) deadlocked the integration suite. The
        # algorithm-level cooldown check inside `recalibrate()` remains as
        # defence in depth.
        # skip_cooldown=True is set when weight delta since last calibration is
        # ≥5 kg (PDF rule: "recalculate every 5 kg lost" — BMR changes with mass).
        current = await self.goals_repo.get_current(user_id)
        if current is None:
            return RecalibrationSkipped("no_baseline")
        days_since = max(0, (_now() - current.valid_from).days)
        if days_since < COOLDOWN_DAYS and not skip_cooldown:
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
        # Same capped goal adjustment as initial goals (bmr_safety.apply_goal_to_tdee).
        kcal_target = int(apply_goal_to_tdee(tdee_val=Decimal(result.tdee_new), goal=bio["goal"]))
        # H1.4 — apply lactation/pregnancy surpluses + enforce BMR safety
        # floor on the FINAL target. Same precedence as `_build_goals`.
        kcal_target = _adjust_and_enforce_floor(
            user_id=user_id,
            kcal_target_int=kcal_target,
            bmr_int=result.bmr_new,
            conditions=frozenset(bio.get("conditions") or ()),
            trimester=bio.get("trimester"),
            is_exclusively_breastfeeding=bio.get("is_exclusively_breastfeeding"),
        )
        pw = _protein_weight(bio["weight_kg"], bio["height_cm"])
        macros = compute_macros(
            kcal_target=kcal_target, weight_kg=pw, goal=bio["goal"]
        )
        krange = to_range(kcal_target)
        # NOVA hydration v2 — `calculate_water_target` honours kcal load,
        # climate, pregnancy/lactation and the CKD/CHF medical override.
        water = _compute_water_target_ml(
            weight_kg=bio["weight_kg"],
            kcal_daily=kcal_target,
            activity_level=bio["activity_level"],
            goal=bio["goal"],
            conditions=frozenset(bio.get("conditions") or ()),
            region=bio.get("region"),
            pregnant=bool(bio.get("pregnant")),
            lactating=bool(bio.get("lactating")),
        )
        fiber_target_g = max(1, int(round(kcal_target / 1000 * 14)))
        if bio.get("goal") == "weight_loss":
            fiber_target_g = max(fiber_target_g, 30)
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
            fiber_target_g=fiber_target_g,
            sodium_target_mg=2000,
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
class GetWeightInsights:
    """Compute ideal-weight metrics on-the-fly from biometrics.

    Pure computation — no DB write, no state change. Returns None when
    biometrics are incomplete (weight_kg, height_cm, sex required).
    """

    profile_reader: ProfileReader

    async def __call__(self, *, user_id: UUID) -> "WeightInsights | None":
        from app.nutrition.domain.ideal_weight import (
            DEFAULT_WEEKLY_RATE,
            WeightInsights,
            compute_weight_insights,
        )

        bio = await self.profile_reader.biometrics(user_id)
        if not bio:
            return None
        weight_kg = bio.get("weight_kg")
        height_cm = bio.get("height_cm")
        sex = bio.get("sex")
        if not all((weight_kg, height_cm, sex)):
            return None
        return compute_weight_insights(
            weight_kg=weight_kg,
            height_cm=height_cm,
            sex=sex,
            goal=bio.get("goal", "weight_maintenance"),
            is_pregnant=bool(bio.get("pregnant")),
            weekly_rate_kg=DEFAULT_WEEKLY_RATE,
        )


@dataclass(slots=True)
class GetWeightProgress:
    """Compute read-only weight trend from last 14-day weigh-in series.

    Non-fatal: returns None when user has insufficient data (< 7 weight points).
    Never triggers recalibration — pure observation.
    """

    profile_reader: ProfileReader
    tracking_reader: TrackingReader

    async def __call__(self, *, user_id: UUID) -> "WeightProgress | None":
        from app.nutrition.domain.ideal_weight import (
            DEFAULT_WEEKLY_RATE,
            compute_weight_insights,
        )
        from app.nutrition.domain.weight_progress import (
            WeightProgress,
            compute_weight_progress,
        )

        bio = await self.profile_reader.biometrics(user_id)
        if not bio:
            return None

        weights = await self.tracking_reader.weight_series_14d(user_id)

        # Resolve weight_to_lose_kg from insights if we have enough biometrics
        weight_to_lose_kg = None
        if bio.get("weight_kg") and bio.get("height_cm") and bio.get("sex"):
            wi = compute_weight_insights(
                weight_kg=bio["weight_kg"],
                height_cm=bio["height_cm"],
                sex=bio["sex"],
                goal=bio.get("goal", "weight_maintenance"),
                is_pregnant=bool(bio.get("pregnant")),
                weekly_rate_kg=DEFAULT_WEEKLY_RATE,
            )
            weight_to_lose_kg = wi.weight_to_lose_kg

        return compute_weight_progress(
            weights=weights,
            weight_to_lose_kg=weight_to_lose_kg,
            goal=bio.get("goal", "weight_maintenance"),
            target_weekly_rate_kg=DEFAULT_WEEKLY_RATE,
        )


@dataclass(slots=True)
class GetGoalsHistory:
    goals_repo: NutritionalGoalsRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        limit: int = 20,
        cursor: datetime | None = None,
    ) -> list[NutritionalGoals]:
        return await self.goals_repo.list_history(user_id, limit, cursor=cursor)


@dataclass(slots=True)
class GetWeeklySummary:
    """Aggregate the last 7 days of food + water logs vs nutritional targets.

    Returns a dict ready for the weekly-summary endpoint schema. Aggregates
    directly from raw food_logs (the former daily-aggregate matview was
    unpopulated under the no-cron rule, so querying it raised and poisoned
    the session; dropped in migration 0029). All queries are read-only and
    share the caller's session.
    """

    session: AsyncSession

    async def __call__(self, *, user_id: UUID) -> dict:
        uid = str(user_id)

        # --- targets ---
        targets_row = (
            await self.session.execute(
                text(
                    """
                    SELECT kcal_min, kcal_max, protein_g, water_ml
                      FROM nutritional_goals
                     WHERE user_id = :uid
                     ORDER BY valid_from DESC
                     LIMIT 1
                """
                ),
                {"uid": uid},
            )
        ).mappings().first()

        kcal_target = int((targets_row["kcal_min"] + targets_row["kcal_max"]) / 2) if targets_row else 0
        protein_target = int(targets_row["protein_g"]) if targets_row else 0
        water_target_ml = int(targets_row["water_ml"]) if targets_row else 0

        # --- daily food totals last 7 days ---
        daily_rows = (
            await self.session.execute(
                text(
                    """
                    SELECT date AS day,
                           COALESCE(SUM(kcal), 0)::int AS kcal,
                           COALESCE(SUM(protein_g), 0)::int AS protein_g
                      FROM food_logs
                     WHERE user_id = :uid
                       AND date >= CURRENT_DATE - 6
                     GROUP BY date
                     ORDER BY day ASC
                """
                ),
                {"uid": uid},
            )
        ).mappings().all()

        days_with_logs = {r["day"] for r in daily_rows if int(r["kcal"] or 0) > 0}
        logged_days = len(days_with_logs)
        avg_kcal = int(sum(int(r["kcal"] or 0) for r in daily_rows) / max(logged_days, 1))
        avg_protein_g = int(sum(int(r["protein_g"] or 0) for r in daily_rows) / max(logged_days, 1))

        # --- water today ---
        water_row = (
            await self.session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(ml), 0)::int AS total_ml
                      FROM water_logs
                     WHERE user_id = :uid AND logged_at::date = CURRENT_DATE
                """
                ),
                {"uid": uid},
            )
        ).mappings().first()
        water_today_ml = int(water_row["total_ml"]) if water_row else 0

        # --- streak (consecutive days with food logs, ending today) ---
        streak_row = (
            await self.session.execute(
                text(
                    """
                    WITH logged AS (
                        SELECT DISTINCT date AS d
                          FROM food_logs
                         WHERE user_id = :uid
                    ),
                    series AS (
                        SELECT d,
                               d - ROW_NUMBER() OVER (ORDER BY d)::int * INTERVAL '1 day' AS grp
                          FROM logged
                    )
                    SELECT COUNT(*) AS streak
                      FROM series
                     WHERE grp = (
                         SELECT grp FROM series
                          WHERE d = CURRENT_DATE
                          LIMIT 1
                     )
                """
                ),
                {"uid": uid},
            )
        ).mappings().first()
        streak_days = int(streak_row["streak"]) if streak_row and streak_row["streak"] else 0

        # kcal logged today — extracted from daily_rows (already fetched above)
        # Avoids a 5th round-trip; daily_rows covers CURRENT_DATE via >= CURRENT_DATE - 6.
        _today_row = next((r for r in daily_rows if r["day"] == date.today()), None)
        kcal_today = int(_today_row["kcal"] or 0) if _today_row else 0
        # Positive = surplus (ate more than target); negative = deficit (good for weight_loss)
        kcal_delta_today = kcal_today - kcal_target

        return {
            "logged_days": logged_days,
            "window_days": 7,
            "avg_kcal": avg_kcal,
            "kcal_target": kcal_target,
            "avg_protein_g": avg_protein_g,
            "protein_target_g": protein_target,
            "water_today_ml": water_today_ml,
            "water_target_ml": water_target_ml,
            "streak_days": streak_days,
            "kcal_today": kcal_today,
            "kcal_delta_today": kcal_delta_today,
        }
