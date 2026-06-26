"""create_plan use case — Layer1 → Layer2 → Layer3 → Layer4 orchestrator.

Algorithm (per day, per meal slot):
  1. Layer 1 yields eligible candidate IDs (region/allergens/conditions).
     Cached per meal_time for the whole generation (catalog is static
     within one run).
  2. Layer 2 picks the top-20 macro-balanced shortlist (kcal/protein
     fit) honouring the repetition cap (rolling forbidden window: 7 days
     for day/week plans, 14 days for month plans) plus same-day
     cross-slot dedup. If the cap starves the pool, it is relaxed
     progressively (history first, then same-day) — safety filters are
     never relaxed, they live in Layer 1.
  3. Layer 3 ranks the shortlist with the taste-EMA composite, fed with
     real novelty counts (recipe occurrences in the user's plans over
     the last 30 days, updated in-generation as slots are filled) and
     adherence rates (historical completion per recipe).
  4. Seeded stochastic pick over the top-5 ranked candidates (geometric
     weights) — same seed + same DB state reproduces the same plan
     (novelty counts and catalog contents are inputs too); a fresh seed
     yields a different-but-equally-good plan, so regeneration never
     returns an identical plan and month plans don't cycle the same week.
  5. Layer 4 runs a single LLM coherence pass over the candidate plan and
     applies validated swaps from the per-slot alternatives map.
  6. Persist plan + days + meals + seed via the repository.

Per-meal kcal/protein shares follow the slot-weight distribution
(`_SLOT_WEIGHTS`) instead of a uniform split, and the divisor is the
number of slots actually generated, so daily totals close to the target
even when `meals_per_day` exceeds the available slot set. Layer 4 is
best-effort: failures return the unmodified plan.
"""

from __future__ import annotations

import asyncio
import random
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

# Per-slot kcal/protein distribution (replaces the old uniform split).
# Keyed by number of generated slots; values follow `meal_times` order
# (breakfast, lunch, dinner, snack). Nutrition rationale: lunch is the
# largest intake in LatAm/EU eating patterns; snack is a light bridge.
_SLOT_WEIGHTS: dict[int, tuple[float, ...]] = {
    1: (1.0,),
    2: (0.45, 0.55),
    3: (0.30, 0.40, 0.30),
    4: (0.25, 0.35, 0.30, 0.10),
}

# weight_gain distribution (nutrition expert 2026-06-16): a high surplus target
# is hit with MORE eating occasions + energy-dense food, NOT a single giant
# plate (early satiety kills adherence). Flatter weights keep every slot's kcal
# share reachable by scaling a normal recipe within bounds (no slot >30%), and
# weight_gain forces the snack slot in so 4 occasions exist.
_SLOT_WEIGHTS_GAIN: dict[int, tuple[float, ...]] = {
    1: (1.0,),
    2: (0.5, 0.5),
    3: (0.30, 0.35, 0.35),
    4: (0.25, 0.30, 0.25, 0.20),
}

# Geometric sampling weights over the top-5 Layer3 candidates. Rank 1
# stays the most likely pick (~52%) so quality is preserved, while the
# tail introduces enough seeded variety that two generations (different
# seeds) or two weeks of a month plan don't repeat the same sequence.
_PICK_WEIGHTS: tuple[float, ...] = (8.0, 4.0, 2.0, 1.0, 0.5)

# Portion-scaling bounds. A meal is scaled so its kcal hits the slot share, but
# only within a realistic range — a drink can't sanely become 3× and a dense
# plate shouldn't shrink to a quarter. 1.0 = unscaled.
_MIN_SCALE: float = 0.5
_MAX_SCALE: float = 2.0


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
    meal_times: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")

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

        # Gather independent startup DB calls in a single round-trip.
        targets, profile, ranking_ctx = await asyncio.gather(
            self.user_ctx.get_user_targets(user_id),
            self.user_ctx.get_user_profile_snapshot(user_id),
            self.layer3.profile_ctx.get_ranking_context(user_id),
        )
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
        kcal_daily = int(targets.get("kcal_max") or targets.get("kcal_min") or 2000)
        protein_daily = int(targets.get("protein_g") or 100)
        goal = str(targets.get("goal") or "").lower()
        prefer_dense = goal == "weight_gain"
        meals_per_day = int(targets.get("meals_per_day") or self.meals_per_day_default)
        # weight_gain spreads intake across more occasions so no single meal
        # needs an unrealistic >2x portion to hit a high surplus target — force
        # the snack slot in (nutrition expert 2026-06-16).
        if prefer_dense:
            meals_per_day = max(meals_per_day, 4)
        # The kcal/protein divisor is the number of slots actually
        # generated. Previously `meals_per_day=5` divided the day into 5
        # shares but only 3 slots existed → the plan silently delivered
        # ~60% of the daily target.
        slots = self.meal_times[: max(1, min(meals_per_day, len(self.meal_times)))]
        weight_table = _SLOT_WEIGHTS_GAIN if prefer_dense else _SLOT_WEIGHTS
        weights = weight_table.get(len(slots)) or tuple(1.0 / len(slots) for _ in slots)
        kcal_share_by_slot = {
            mt: max(1, int(round(kcal_daily * w))) for mt, w in zip(slots, weights, strict=False)
        }
        protein_share_by_slot = {
            mt: max(1, int(round(protein_daily * w))) for mt, w in zip(slots, weights, strict=False)
        }

        # Slot targets: persisted on the plan so iOS can show target vs actual
        # per slot without re-deriving from goals + weights.
        slot_targets: dict[str, dict[str, int]] = {
            mt: {"kcal": kcal_share_by_slot[mt], "protein_g": protein_share_by_slot[mt]}
            for mt in slots
        }

        plan_id = uuid4()
        now = datetime.now(UTC)
        days: list[PlanDay] = []
        rng = random.Random(seed)  # noqa: S311 — meal variety sampling, not crypto; seeded for reproducibility

        # Real historical signals for Layer3 (previously never wired, so
        # novelty was constant 1.0 and adherence constant 0.5 — 20% of the
        # composite score was dead weight). `novelty_counts` is also
        # updated in-generation so a month plan penalises recipes already
        # used in earlier weeks of the same plan.
        novelty_counts = dict(
            await self.plans.count_recent_recipe_occurrences(user_id, days=30)
        )
        adherence_rates = await self.plans.recipe_completion_rates(user_id)

        # Rolling forbidden window, by meal_time: 7 days for day/week
        # plans, 14 for month plans (a 7-day window let deterministic
        # picks cycle the exact same week 4×).
        window_days = 7 if total_days <= 7 else 14
        forbidden: dict[str, set[UUID]] = {mt: set() for mt in slots}
        forbidden_window: list[tuple[int, str, UUID]] = []  # (day_index, mt, rid)
        alternatives_by_slot: dict[tuple[int, str], list[str]] = {}
        # Layer1 candidates are stable within one generation run — cache
        # per meal_time instead of re-querying per day (month plan: 120
        # identical queries → 4).
        layer1_cache: dict[str, list[UUID]] = {}
        # Shared embedding cache: recipe embeddings fetched once per unique
        # recipe_id and reused across all Layer3 calls. Month plan: up to
        # 120 calls sharing ~200-400 unique recipes → 99%+ cache hits after
        # day 1 per meal_time. Dict populated in-place by Layer3.__call__.
        embedding_cache: dict[UUID, tuple[list[str], int | None, list[float]]] = {}

        for d in range(total_days):
            day_id = uuid4()
            meals: list[PlanMeal] = []
            chosen_today: set[UUID] = set()
            for mt in slots:
                t0 = time.perf_counter()
                if mt not in layer1_cache:
                    layer1_cache[mt] = await self.layer1(user_id=user_id, meal_time=mt)
                cand_ids = layer1_cache[mt]
                _layer_hist.labels(layer="1").observe(time.perf_counter() - t0)

                t0 = time.perf_counter()
                kcal_share = kcal_share_by_slot[mt]
                protein_share = protein_share_by_slot[mt]
                shortlist = await self.layer2(
                    candidate_ids=cand_ids,
                    meal_time=mt,
                    kcal_target_share=kcal_share,
                    protein_target_share=protein_share,
                    # Cross-slot dedup: never serve the same recipe twice
                    # in one day, regardless of slot.
                    forbidden_ids=forbidden[mt] | chosen_today,
                    top_k=20,
                    prefer_dense=prefer_dense,
                )
                if not shortlist and (forbidden[mt] or chosen_today):
                    # Repetition cap starved the pool (small catalog for
                    # this user's allergen/condition profile). Variety is
                    # a preference, not a safety rule — relax history
                    # first, then same-day dedup, rather than serving a
                    # partial day. Safety filters live in Layer1 and are
                    # never relaxed.
                    shortlist = await self.layer2(
                        candidate_ids=cand_ids,
                        meal_time=mt,
                        kcal_target_share=kcal_share,
                        protein_target_share=protein_share,
                        forbidden_ids=chosen_today,
                        top_k=20,
                        prefer_dense=prefer_dense,
                    )
                if not shortlist and chosen_today:
                    shortlist = await self.layer2(
                        candidate_ids=cand_ids,
                        meal_time=mt,
                        kcal_target_share=kcal_share,
                        protein_target_share=protein_share,
                        forbidden_ids=set(),
                        top_k=20,
                        prefer_dense=prefer_dense,
                    )
                _layer_hist.labels(layer="2").observe(time.perf_counter() - t0)

                t0 = time.perf_counter()
                ranked = await self.layer3(
                    user_id=user_id,
                    candidate_ids=[rid for rid, _ in shortlist],
                    meal_time=mt,
                    novelty_counts=novelty_counts,
                    adherence_rates=adherence_rates,
                    ranking_context=ranking_ctx,
                    embedding_cache=embedding_cache,
                )
                _layer_hist.labels(layer="3").observe(time.perf_counter() - t0)

                if not ranked:
                    # No candidate: skip meal rather than fail-hard. The
                    # generator surfaces this as a partial day; UI can offer
                    # manual override.
                    continue
                # Seeded stochastic pick over the top-5: same seed →
                # same plan (reproducible); new seed → fresh-but-good
                # plan. Replaces the old deterministic ranked[0] pick
                # that made every regeneration identical.
                top = ranked[: len(_PICK_WEIGHTS)]
                chosen = rng.choices(
                    [rid for rid, _ in top],
                    weights=_PICK_WEIGHTS[: len(top)],
                    k=1,
                )[0]
                alternatives_by_slot[(d, mt)] = [
                    str(rid) for rid, _ in ranked[:6] if rid != chosen
                ][:5]

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
                chosen_today.add(chosen)
                novelty_counts[chosen] = novelty_counts.get(chosen, 0) + 1

            # Slide repetition window: drop entries older than window_days.
            cutoff = d - (window_days - 1)
            forbidden_window = [t for t in forbidden_window if t[0] >= cutoff]
            forbidden = {mt: set() for mt in slots}
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
            # Honest value: the number of slots actually generated (a
            # request for 5 meals clamps to the 4 available slots).
            meals_per_day=len(slots),
            preferences=preferences or [],
            kcal_target=kcal_daily,
            version=0,
            created_at=now,
            days=days,
            water_view=water_view,
            slot_targets=slot_targets,
        )
        # Per-meal macros (2026-06-11 root-cause fix). Persisting plans
        # with NULL kcal/protein/carbs/fat broke the iOS plan screen — UI
        # rendered each meal as nutritional zero. Layer3 picks a recipe
        # for each slot; recipes already carry their own kcal+macro totals
        # in `recipes.{kcal,protein_g,carbs_g,fat_g}`. We batch-fetch them
        # in a single query (typically ~15 unique recipes across 21 meals
        # due to weekly repetition) and project them onto each PlanMeal
        # BEFORE persistence. Layer4 swaps may have changed `recipe_id`,
        # so this step must run AFTER Layer4 and BEFORE save.
        all_recipe_ids = [
            m.recipe_id for d in days for m in d.meals if m.recipe_id is not None
        ]
        if all_recipe_ids:
            macros = await self.plans.fetch_recipe_macros(all_recipe_ids)
            for d in days:
                for m in d.meals:
                    if m.recipe_id is None:
                        continue
                    row = macros.get(m.recipe_id)
                    if row is None:
                        continue
                    n_kcal, n_prot, n_carb, n_fat, r_scale_min, r_scale_max = row
                    # Portion scaling: use per-recipe bounds when the v3 catalog
                    # supplies them; fall back to global constants for legacy rows.
                    s_min = r_scale_min if r_scale_min is not None else _MIN_SCALE
                    s_max = r_scale_max if r_scale_max is not None else _MAX_SCALE
                    target = kcal_share_by_slot.get(m.meal_time)
                    factor = 1.0
                    if n_kcal and target:
                        factor = max(s_min, min(s_max, target / n_kcal))
                    m.kcal = int(round((n_kcal or 0) * factor))
                    m.protein_g = int(round((n_prot or 0) * factor))
                    m.carbs_g = int(round((n_carb or 0) * factor))
                    m.fat_g = int(round((n_fat or 0) * factor))
                    m.scaled_factor = round(factor, 3)

                # withinBand: validate day kcal closes near target (±20 %).
                # Computed after macro hydration so scaled values are final.
                d.kcal_actual = sum(m.kcal or 0 for m in d.meals)
                if kcal_daily > 0 and d.kcal_actual > 0:
                    deviation = abs(d.kcal_actual - kcal_daily) / kcal_daily
                    d.within_band = deviation <= 0.20
                    if not d.within_band:
                        log.warning(
                            "plan.day_outside_band",
                            day=d.day_index,
                            kcal_actual=d.kcal_actual,
                            kcal_target=kcal_daily,
                            deviation_pct=round(deviation * 100, 1),
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
