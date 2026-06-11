"""create_plan use case — Layer1 → Layer2 → Layer3 → Layer4 orchestrator.

Algorithm (per day, per meal slot):
  1. Layer 1 yields eligible candidate IDs (region/allergens/conditions).
  2. Layer 2 picks the top-20 macro-balanced shortlist (kcal/protein
     residuals) honouring repetition cap (rolling 7-day forbidden set).
  3. Layer 3 ranks the shortlist with the taste-EMA composite.
  4. Layer 4 runs a single LLM coherence pass over the candidate plan and
     applies validated swaps from the per-slot alternatives map.
  5. Persist plan + days + meals + seed via the repository.

Per-meal-slot kcal share = daily kcal / meals_per_day; per-meal protein
share = daily protein / meals_per_day. Layer 4 is best-effort: failures
return the unmodified plan.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from prometheus_client import Histogram

from app.core.errors import BusinessRuleViolation
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.plan.application.layer1_eligibility import Layer1Eligibility
from app.plan.application.layer2_shortlist import Layer2Shortlist
from app.plan.application.layer3_ranking import Layer3Ranking
from app.plan.application.layer4_coherence import Layer4Coherence
from app.plan.domain.entities import Plan, PlanDay, PlanMeal
from app.plan.domain.events import PlanCreated
from app.plan.domain.value_objects import PLAN_TYPE_TO_DAYS, PlanType
from app.plan.domain.water_view import build_water_view
from app.plan.infrastructure.repositories import SqlPlanRepository
from app.shared.i18n.locale_resolver import Locale

log = get_logger("plan.create")

_layer_hist = Histogram(
    "plan_generation_layer_duration_seconds",
    "Wall-clock time per plan generation layer",
    ["layer"],
    buckets=(0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 3.0, 10.0),
)


class _UserContext(Protocol):
    async def get_user_targets(self, user_id: UUID) -> dict: ...
    async def get_user_profile_snapshot(self, user_id: UUID) -> dict: ...


class _EnsureGoalsPort(Protocol):
    """Defense-in-depth: compute nutritional goals inline if missing.

    Set by the worker wiring (`worker/plan_tasks.py`) so that when the
    upstream event-driven baseline somehow failed to materialise (legacy
    rows, external publisher, etc.) we never produce a plan with empty
    `plan_meals`. When the port is `None` and goals are missing, the
    plan generation raises rather than silently degrading.
    """

    async def __call__(self, *, user_id: UUID) -> None: ...


@dataclass(slots=True)
class CreatePlan:
    plans: SqlPlanRepository
    layer1: Layer1Eligibility
    layer2: Layer2Shortlist
    layer3: Layer3Ranking
    layer4: Layer4Coherence
    user_ctx: _UserContext
    bus: EventBus
    ensure_goals: _EnsureGoalsPort | None = None
    meals_per_day_default: int = 3
    meal_times: tuple[str, ...] = ("breakfast", "lunch", "dinner")

    async def __call__(
        self,
        *,
        user_id: UUID,
        plan_type: PlanType,
        seed: int | None = None,
        preferences: list[str] | None = None,
        locale: Locale | None = None,
    ) -> Plan:
        total_days = PLAN_TYPE_TO_DAYS[plan_type]
        seed = seed if seed is not None else secrets.randbits(63)

        targets = await self.user_ctx.get_user_targets(user_id)
        # Defense-in-depth invariant — NEVER generate a plan against the
        # 2000 kcal fallback. If `nutritional_goals` is missing, recover
        # by computing the baseline inline (idempotent); if that path is
        # not wired or fails, abort BEFORE the plan row is created so we
        # never persist an empty plan. Owner directive 2026-06-09:
        # "no debería crear planes con nada, eso está mal, siempre
        # tiene que generar un plan".
        if not targets:
            if self.ensure_goals is None:
                raise BusinessRuleViolation("nutritional_goals_missing")
            try:
                await self.ensure_goals(user_id=user_id)
            except Exception as exc:
                log.error(
                    "plan.ensure_goals_failed",
                    user_id=str(user_id),
                    error=str(exc),
                )
                raise BusinessRuleViolation("nutritional_goals_unavailable") from exc
            targets = await self.user_ctx.get_user_targets(user_id)
            if not targets:
                raise BusinessRuleViolation("nutritional_goals_missing")
        profile = await self.user_ctx.get_user_profile_snapshot(user_id)
        kcal_daily = int(targets.get("kcal_max") or targets.get("kcal_min") or 2000)
        protein_daily = int(targets.get("protein_g") or 100)
        meals_per_day = int(targets.get("meals_per_day") or self.meals_per_day_default)
        kcal_share = kcal_daily // max(1, meals_per_day)
        protein_share = protein_daily // max(1, meals_per_day)

        plan_id = uuid4()
        now = datetime.now(UTC)
        days: list[PlanDay] = []

        # rolling 7-day forbidden set, by meal_time, for repetition cap.
        forbidden: dict[str, set[UUID]] = {mt: set() for mt in self.meal_times}
        forbidden_window: list[tuple[int, str, UUID]] = []  # (day_index, mt, rid)
        alternatives_by_slot: dict[tuple[int, str], list[str]] = {}

        for d in range(total_days):
            day_id = uuid4()
            meals: list[PlanMeal] = []
            for mt in self.meal_times[:meals_per_day]:
                t0 = time.perf_counter()
                cand_ids = await self.layer1(user_id=user_id, meal_time=mt)
                _layer_hist.labels(layer="1").observe(time.perf_counter() - t0)

                t0 = time.perf_counter()
                shortlist = await self.layer2(
                    candidate_ids=cand_ids,
                    meal_time=mt,
                    kcal_target_share=kcal_share,
                    protein_target_share=protein_share,
                    forbidden_ids=forbidden[mt],
                    top_k=20,
                )
                _layer_hist.labels(layer="2").observe(time.perf_counter() - t0)

                t0 = time.perf_counter()
                ranked = await self.layer3(
                    user_id=user_id,
                    candidate_ids=[rid for rid, _ in shortlist],
                    meal_time=mt,
                )
                _layer_hist.labels(layer="3").observe(time.perf_counter() - t0)

                if not ranked:
                    # No candidate: skip meal rather than fail-hard. The
                    # generator surfaces this as a partial day; UI can offer
                    # manual override.
                    continue
                chosen, _ = ranked[0]
                alternatives_by_slot[(d, mt)] = [str(rid) for rid, _ in ranked[1:6]]

                meal_id = uuid4()
                meals.append(
                    PlanMeal(
                        id=meal_id,
                        plan_day_id=day_id,
                        meal_time=mt,  # type: ignore[arg-type]
                        recipe_id=chosen,
                        kcal=None,
                        protein_g=None,
                        carbs_g=None,
                        fat_g=None,
                    )
                )
                forbidden_window.append((d, mt, chosen))
                forbidden[mt].add(chosen)

            # Slide repetition window: drop entries older than 7 days.
            cutoff = d - 6
            forbidden_window = [t for t in forbidden_window if t[0] >= cutoff]
            forbidden = {mt: set() for mt in self.meal_times}
            for _, mt, rid in forbidden_window:
                forbidden[mt].add(rid)

            days.append(
                PlanDay(
                    id=day_id,
                    plan_id=plan_id,
                    day_index=d,
                    date=(now.date() + timedelta(days=d)),
                    completed=False,
                    meals=meals,
                )
            )

        # Hard invariant — never persist a plan with zero meals across all
        # days. The per-meal Layer3 fall-through (skip when no candidate)
        # is meant for sparse-catalog edge cases; if EVERY slot returns
        # empty, the eligibility/ranking pipeline is misconfigured and
        # the right answer is to fail fast so the worker job errors,
        # not to persist a 7-day shell with no recipes. Outer
        # `session_scope()` rolls back, leaving no plan/plan_days rows.
        total_meals = sum(len(d.meals) for d in days)
        if total_meals == 0:
            raise BusinessRuleViolation("plan_generation_yielded_no_meals")

        # Layer 4 — one LLM call over the whole plan.
        t0 = time.perf_counter()
        candidate_plan_payload = [
            {
                "day": dd.day_index,
                "meals": [
                    {"meal_time": m.meal_time, "recipe_id": str(m.recipe_id)} for m in dd.meals
                ],
            }
            for dd in days
        ]
        try:
            coherence = await self.layer4(
                user_id=user_id,
                user_profile=profile,
                candidate_plan=candidate_plan_payload,
                alternatives_by_slot=alternatives_by_slot,
            )
            for swap in coherence.get("swaps", []) or []:
                day_i = int(swap.get("day", -1))
                mt = swap.get("meal_time")
                new_rid = swap.get("new_recipe_id")
                if 0 <= day_i < len(days) and new_rid:
                    for meal in days[day_i].meals:
                        if meal.meal_time == mt:
                            meal.swapped_from = meal.recipe_id
                            meal.recipe_id = UUID(new_rid)
        except Exception as exc:  # noqa: BLE001
            log.warning("plan.layer4_failed", error=str(exc))
        _layer_hist.labels(layer="4").observe(time.perf_counter() - t0)

        # Daily hydration view — sourced from `nutritional_goals.water_ml`
        # (already produced by the nutrition use case via
        # `calculate_water_target`). Single source of truth; never
        # recomputed here.
        water_ml = targets.get("water_ml")
        # Locale precedence (D1): explicit request locale > profile.locale > "es".
        # The use case is invoked from (1) the API task enqueuer, which resolves
        # locale from `Accept-Language`/profile via `LocaleDep`, and (2) the Arq
        # worker, which forwards the request-time locale through the job
        # payload. Profile fallback covers legacy callers that have not yet
        # been threaded through Phase 2 wiring.
        effective_locale: str = locale or str(profile.get("locale") or "es")
        water_view = (
            build_water_view(
                total_ml=int(water_ml),
                locale=effective_locale,
            )
            if water_ml is not None and int(water_ml) > 0
            else None
        )

        plan = Plan(
            id=plan_id,
            user_id=user_id,
            type=plan_type,
            total_days=total_days,
            current_day=1,
            status="active",
            goal=str(targets.get("goal") or ""),
            meals_per_day=meals_per_day,
            preferences=preferences or [],
            kcal_target=kcal_daily,
            version=0,
            created_at=now,
            days=days,
            water_view=water_view,
        )
        # Idempotent-by-user invariant (2026-06-11 root-cause fix for iOS
        # plan-create errors). The `one_active_plan` partial unique index
        # on `plans(user_id) WHERE status='active'` made every regeneration
        # request crash with IntegrityError if any active plan already
        # existed (or two concurrent jobs raced). We now:
        #   1. Acquire a per-user pg_advisory_xact_lock so concurrent
        #      worker jobs for the same user serialise (backlog drain,
        #      double-tap, retry storms).
        #   2. Archive the existing active plan in-tx → frees the partial
        #      unique slot. End state: at most one active plan per user,
        #      "regenerate" semantics match the iOS mental model.
        # Lock released automatically on commit/rollback. DB constraint
        # stays as belt-and-suspenders against future regressions.
        await self.plans.acquire_user_lock(user_id)
        await self.plans.archive_active(user_id)
        await self.plans.save(plan)
        await self.plans.save_seed(plan_id, seed)
        await self.bus.publish(
            PlanCreated(
                plan_id=plan_id,
                user_id=user_id,
                type=plan_type,
                total_days=total_days,
                at=now,
            )
        )
        return plan
