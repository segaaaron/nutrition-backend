"""Invariants for `CreatePlan` after the empty-plan_meals incident
(2026-06-09).

Owner directive: "no debería crear planes con nada, eso está mal,
siempre tiene que generar un plan". The use case must:

1. Refuse to start when `nutritional_goals` are missing AND no
   `ensure_goals` adapter is wired (no silent 2000-kcal fallback).
2. Recover transparently when `ensure_goals` IS wired by computing
   the baseline inline (defense-in-depth for legacy users).
3. NEVER persist a plan if the generation pipeline yields zero meals
   across all days — the outer `session_scope()` rolls back so no
   `plans` / `plan_days` rows remain.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.errors import BusinessRuleViolation
from app.core.event_bus import EventBus
from app.plan.application.create_plan import CreatePlan


class _StubPlans:
    def __init__(self) -> None:
        self.saved: list[Any] = []
        self.seeds: list[tuple[UUID, int]] = []
        self.locks: list[UUID] = []
        self.archived_for: list[UUID] = []

    async def acquire_user_lock(self, user_id: UUID) -> None:
        self.locks.append(user_id)

    async def archive_active(self, user_id: UUID) -> int:
        self.archived_for.append(user_id)
        return 0

    async def fetch_recipe_macros(
        self, recipe_ids: list[UUID]
    ) -> dict[UUID, tuple[int | None, int | None, int | None, int | None, float | None, float | None]]:
        # Deterministic macros so tests can assert population.
        # (kcal, protein_g, carbs_g, fat_g, scale_min, scale_max)
        return {rid: (500, 30, 50, 15, None, None) for rid in recipe_ids}

    async def count_recent_recipe_occurrences(
        self, user_id: UUID, *, days: int = 30
    ) -> dict[UUID, int]:
        return {}

    async def recipe_completion_rates(
        self, user_id: UUID, *, days: int = 90
    ) -> dict[UUID, float]:
        return {}

    async def save(self, plan: Any) -> Any:
        self.saved.append(plan)
        return plan

    async def save_seed(self, plan_id: UUID, seed: int) -> None:
        self.seeds.append((plan_id, seed))


class _StubUserContext:
    def __init__(self, *, targets: dict[str, Any], profile: dict[str, Any]) -> None:
        self._targets = targets
        self._profile = profile
        self.targets_calls = 0

    async def get_user_targets(self, user_id: UUID) -> dict[str, Any]:
        self.targets_calls += 1
        return self._targets

    async def get_user_profile_snapshot(self, user_id: UUID) -> dict[str, Any]:
        return self._profile


class _Layer1Empty:
    async def __call__(self, *, user_id: UUID, meal_time: str) -> list[UUID]:
        return []


class _Layer2Empty:
    async def __call__(
        self,
        *,
        candidate_ids: list[UUID],
        meal_time: str,
        kcal_target_share: int,
        protein_target_share: int,
        forbidden_ids: set[UUID],
        top_k: int,
        prefer_dense: bool = False,
    ) -> list[tuple[UUID, float]]:
        return []


class _ProfileCtxNoOp:
    async def get_ranking_context(self, user_id: UUID) -> dict:  # type: ignore[override]
        return {}


class _Layer3Empty:
    profile_ctx = _ProfileCtxNoOp()

    async def __call__(
        self,
        *,
        user_id: UUID,
        candidate_ids: list[UUID],
        meal_time: str,
        novelty_counts: dict[UUID, int] | None = None,
        adherence_rates: dict[UUID, float] | None = None,
        ranking_context: dict | None = None,
        embedding_cache: dict | None = None,
    ) -> list[tuple[UUID, float]]:
        return []


class _Layer4NoOp:
    async def __call__(
        self,
        *,
        user_id: UUID,
        user_profile: dict,
        candidate_plan: list[dict],
        alternatives_by_slot: dict[tuple[int, str], list[str]],
    ) -> dict:
        return {}


def _valid_targets() -> dict[str, Any]:
    return {
        "kcal_min": 1700,
        "kcal_max": 1900,
        "protein_g": 140,
        "carbs_g": 180,
        "fat_g": 60,
        "water_ml": 2500,
    }


def _build_uc(
    *,
    targets: dict[str, Any],
    ensure_goals: Any | None = None,
    plans: _StubPlans | None = None,
) -> tuple[CreatePlan, _StubUserContext, _StubPlans]:
    plans = plans or _StubPlans()
    ctx = _StubUserContext(targets=targets, profile={"locale": "es"})
    uc = CreatePlan(
        plans=plans,  # type: ignore[arg-type]
        layer1=_Layer1Empty(),  # type: ignore[arg-type]
        layer2=_Layer2Empty(),  # type: ignore[arg-type]
        layer3=_Layer3Empty(),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=ctx,  # type: ignore[arg-type]
        bus=EventBus(),
        ensure_goals=ensure_goals,
    )
    return uc, ctx, plans


@pytest.mark.asyncio
async def test_create_plan_raises_when_goals_missing_and_no_adapter() -> None:
    uc, _, plans = _build_uc(targets={}, ensure_goals=None)

    with pytest.raises(BusinessRuleViolation, match="nutritional_goals_missing"):
        await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert plans.saved == []
    assert plans.seeds == []


@pytest.mark.asyncio
async def test_create_plan_auto_computes_goals_when_missing() -> None:
    """`ensure_goals` adapter recovers from a missing baseline by
    populating it inline; the second `get_user_targets` call must
    then return the freshly-computed targets so the generator can run.
    """
    targets_holder = {"v": {}}  # mutated by the adapter

    class _RecoveringEnsureGoals:
        def __init__(self) -> None:
            self.called_with: list[UUID] = []

        async def __call__(self, *, user_id: UUID) -> None:
            self.called_with.append(user_id)
            targets_holder["v"] = _valid_targets()

    class _CtxBackedByHolder:
        def __init__(self) -> None:
            self.targets_calls = 0

        async def get_user_targets(self, user_id: UUID) -> dict[str, Any]:
            self.targets_calls += 1
            return dict(targets_holder["v"])

        async def get_user_profile_snapshot(self, user_id: UUID) -> dict[str, Any]:
            return {"locale": "es"}

    adapter = _RecoveringEnsureGoals()
    ctx = _CtxBackedByHolder()
    plans = _StubPlans()
    uc = CreatePlan(
        plans=plans,  # type: ignore[arg-type]
        layer1=_Layer1Empty(),  # type: ignore[arg-type]
        layer2=_Layer2Empty(),  # type: ignore[arg-type]
        layer3=_Layer3Empty(),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=ctx,  # type: ignore[arg-type]
        bus=EventBus(),
        ensure_goals=adapter,
    )

    user_id = uuid4()
    # The Layer3 stub still returns empty → expect the no-meals
    # invariant to fire, but only AFTER the ensure_goals recovery.
    with pytest.raises(BusinessRuleViolation, match="plan_generation_yielded_no_meals"):
        await uc(user_id=user_id, plan_type="week")  # type: ignore[arg-type]

    assert adapter.called_with == [user_id]
    assert ctx.targets_calls == 2  # before + after recovery
    # No partial plan persisted even though the pipeline progressed
    # past the goals check.
    assert plans.saved == []
    assert plans.seeds == []


@pytest.mark.asyncio
async def test_create_plan_never_persists_zero_meal_plan() -> None:
    """Hard invariant: if every meal-slot Layer3 yields no candidate,
    the plan must NOT be persisted. Previous behaviour silently saved
    a Plan + 7 PlanDays with empty meals lists; iOS then rendered
    an empty plan screen.
    """
    uc, _, plans = _build_uc(targets=_valid_targets(), ensure_goals=None)

    with pytest.raises(BusinessRuleViolation, match="plan_generation_yielded_no_meals"):
        await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert plans.saved == [], "plan row leaked despite empty meals"
    assert plans.seeds == [], "seed row leaked despite empty meals"


@pytest.mark.asyncio
async def test_create_plan_succeeds_when_pipeline_yields_meals() -> None:
    """Happy path — at least one meal per day → plan + seed persisted."""
    chosen_recipe = uuid4()

    class _Layer1OK:
        async def __call__(self, *, user_id: UUID, meal_time: str) -> list[UUID]:
            return [chosen_recipe]

    class _Layer2OK:
        async def __call__(self, **kw: Any) -> list[tuple[UUID, float]]:
            return [(chosen_recipe, 1.0)]

    class _Layer3OK:
        profile_ctx = _ProfileCtxNoOp()

        async def __call__(self, **kw: Any) -> list[tuple[UUID, float]]:
            return [(chosen_recipe, 1.0)]

    plans = _StubPlans()
    ctx = _StubUserContext(targets=_valid_targets(), profile={"locale": "es"})
    uc = CreatePlan(
        plans=plans,  # type: ignore[arg-type]
        layer1=_Layer1OK(),  # type: ignore[arg-type]
        layer2=_Layer2OK(),  # type: ignore[arg-type]
        layer3=_Layer3OK(),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=ctx,  # type: ignore[arg-type]
        bus=EventBus(),
    )

    user_id = uuid4()
    plan = await uc(user_id=user_id, plan_type="week")  # type: ignore[arg-type]

    assert len(plans.saved) == 1
    assert len(plans.seeds) == 1
    total_meals = sum(len(d.meals) for d in plan.days)
    assert total_meals > 0
    # Idempotent-by-user invariant (2026-06-11 root-cause fix):
    # CreatePlan must acquire the per-user advisory lock + archive any
    # existing active plan BEFORE inserting the new row, so a backlog
    # drain or concurrent retry never trips `one_active_plan`.
    assert plans.locks == [user_id]
    assert plans.archived_for == [user_id]
    # Per-meal macros populated from the recipe row (2026-06-11: never NULL),
    # AND scaled to the slot's kcal share (2026-06-16 portion scaling). With a
    # 1900 kcal target over 3 slots (30/40/30) the native 500-kcal recipe is
    # scaled per slot, and the day closes to ~1900 instead of summing native
    # weights (3×500=1500, the old ~60-79% drift).
    slot_share = {
        "breakfast": round(1900 * 0.30),
        "lunch": round(1900 * 0.40),
        "dinner": round(1900 * 0.30),
    }
    day_total = sum(m.kcal for m in plan.days[0].meals)
    for m in plan.days[0].meals:
        assert m.kcal == slot_share[m.meal_time], f"{m.meal_time} not scaled to share"
        assert m.scaled_factor is not None and m.scaled_factor > 0
    assert abs(day_total - 1900) <= 3, f"day total {day_total} drifted from 1900"


# ---------------------------------------------------------------------------
# Variety invariants (algorithm 0.2.0): seeded sampling, repetition window,
# cross-slot dedup, slot-weighted kcal shares.
# ---------------------------------------------------------------------------


class _Layer1Pool:
    """Fixed candidate pool per meal_time."""

    def __init__(self, pool: dict[str, list[UUID]]) -> None:
        self.pool = pool
        self.calls = 0

    async def __call__(self, *, user_id: UUID, meal_time: str) -> list[UUID]:
        self.calls += 1
        return list(self.pool.get(meal_time, []))


class _Layer2Filter:
    """Respects forbidden_ids like the real Layer2; stable score order."""

    def __init__(self) -> None:
        self.share_calls: list[tuple[str, int, int]] = []

    async def __call__(
        self,
        *,
        candidate_ids: list[UUID],
        meal_time: str,
        kcal_target_share: int,
        protein_target_share: int,
        forbidden_ids: set[UUID],
        top_k: int,
        prefer_dense: bool = False,
    ) -> list[tuple[UUID, float]]:
        self.share_calls.append((meal_time, kcal_target_share, protein_target_share))
        kept = [cid for cid in candidate_ids if cid not in forbidden_ids]
        return [(cid, 1.0) for cid in kept[:top_k]]


class _Layer3PassThrough:
    profile_ctx = _ProfileCtxNoOp()

    async def __call__(
        self,
        *,
        user_id: UUID,
        candidate_ids: list[UUID],
        meal_time: str,
        novelty_counts: dict[UUID, int] | None = None,
        adherence_rates: dict[UUID, float] | None = None,
        ranking_context: dict | None = None,
        embedding_cache: dict | None = None,
    ) -> list[tuple[UUID, float]]:
        return [(cid, 1.0) for cid in candidate_ids]


def _pool_uc(
    *, pool_size: int = 40, targets: dict[str, Any] | None = None
) -> tuple[CreatePlan, _StubPlans, _Layer1Pool, _Layer2Filter]:
    pool = {
        mt: [uuid4() for _ in range(pool_size)]
        for mt in ("breakfast", "lunch", "dinner", "snack")
    }
    plans = _StubPlans()
    layer1 = _Layer1Pool(pool)
    layer2 = _Layer2Filter()
    ctx = _StubUserContext(
        targets=targets or _valid_targets(), profile={"locale": "es"}
    )
    uc = CreatePlan(
        plans=plans,  # type: ignore[arg-type]
        layer1=layer1,  # type: ignore[arg-type]
        layer2=layer2,  # type: ignore[arg-type]
        layer3=_Layer3PassThrough(),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=ctx,  # type: ignore[arg-type]
        bus=EventBus(),
    )
    return uc, plans, layer1, layer2


@pytest.mark.asyncio
async def test_week_plan_has_no_repeated_recipe_per_slot() -> None:
    uc, _, _, _ = _pool_uc()
    plan = await uc(user_id=uuid4(), plan_type="week", seed=42)  # type: ignore[arg-type]

    for mt in ("breakfast", "lunch", "dinner"):
        picks = [
            m.recipe_id for d in plan.days for m in d.meals if m.meal_time == mt
        ]
        assert len(picks) == 7
        assert len(set(picks)) == 7, f"{mt} repeats within the week"


@pytest.mark.asyncio
async def test_month_plan_does_not_cycle_the_same_week() -> None:
    """Old bug: deterministic ranked[0] + 7-day window made days 8-14
    repeat days 1-7 exactly. With the 14-day window every 14-consecutive-day
    stretch must be repeat-free per slot."""
    uc, _, _, _ = _pool_uc()
    plan = await uc(user_id=uuid4(), plan_type="month", seed=7)  # type: ignore[arg-type]

    assert len(plan.days) == 30
    for mt in ("breakfast", "lunch", "dinner"):
        picks = [
            m.recipe_id for d in plan.days for m in d.meals if m.meal_time == mt
        ]
        for start in range(len(picks) - 13):
            window = picks[start : start + 14]
            assert len(set(window)) == 14, (
                f"{mt}: repeat inside 14-day window starting day {start}"
            )


@pytest.mark.asyncio
async def test_no_recipe_repeats_across_slots_same_day() -> None:
    # Same pool for every slot → without cross-slot dedup the same top
    # recipe would land in breakfast AND lunch AND dinner.
    shared = [uuid4() for _ in range(40)]
    pool = {mt: list(shared) for mt in ("breakfast", "lunch", "dinner", "snack")}
    plans = _StubPlans()
    ctx = _StubUserContext(targets=_valid_targets(), profile={"locale": "es"})
    uc = CreatePlan(
        plans=plans,  # type: ignore[arg-type]
        layer1=_Layer1Pool(pool),  # type: ignore[arg-type]
        layer2=_Layer2Filter(),  # type: ignore[arg-type]
        layer3=_Layer3PassThrough(),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=ctx,  # type: ignore[arg-type]
        bus=EventBus(),
    )
    plan = await uc(user_id=uuid4(), plan_type="week", seed=99)  # type: ignore[arg-type]
    for d in plan.days:
        ids = [m.recipe_id for m in d.meals]
        assert len(ids) == len(set(ids)), f"day {d.day_index} repeats a recipe"


@pytest.mark.asyncio
async def test_same_seed_reproduces_plan_different_seed_varies() -> None:
    uid = uuid4()
    uc1, _, _, _ = _pool_uc()
    plan_a = await uc1(user_id=uid, plan_type="week", seed=1234)  # type: ignore[arg-type]
    # Same pools must be reused for a meaningful comparison.
    uc2 = CreatePlan(
        plans=_StubPlans(),  # type: ignore[arg-type]
        layer1=uc1.layer1,
        layer2=_Layer2Filter(),  # type: ignore[arg-type]
        layer3=_Layer3PassThrough(),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=_StubUserContext(
            targets=_valid_targets(), profile={"locale": "es"}
        ),  # type: ignore[arg-type]
        bus=EventBus(),
    )
    plan_b = await uc2(user_id=uid, plan_type="week", seed=1234)  # type: ignore[arg-type]
    plan_c = await uc2(user_id=uid, plan_type="week", seed=5678)  # type: ignore[arg-type]

    def picks(p: Any) -> list[UUID]:
        return [m.recipe_id for d in p.days for m in d.meals]

    assert picks(plan_a) == picks(plan_b), "same seed must reproduce the plan"
    assert picks(plan_a) != picks(plan_c), "different seed must vary the plan"


@pytest.mark.asyncio
async def test_kcal_shares_close_to_daily_target_even_with_5_meals() -> None:
    """Old bug: meals_per_day=5 divided kcal by 5 but generated only 3
    slots → plan delivered ~60% of the daily target. Now the divisor is
    the generated slot count and shares follow _SLOT_WEIGHTS."""
    targets = {**_valid_targets(), "meals_per_day": 5}
    uc, _, _, layer2 = _pool_uc(targets=targets)
    plan = await uc(user_id=uuid4(), plan_type="day", seed=1)  # type: ignore[arg-type]

    # 5 requested → clamped to the 4 available slots.
    assert plan.meals_per_day == 4
    assert len(plan.days[0].meals) == 4

    kcal_daily = targets["kcal_max"]
    shares = {mt: k for mt, k, _ in layer2.share_calls}
    total_share = sum(shares.values())
    assert abs(total_share - kcal_daily) <= 4, (
        f"slot shares {shares} sum to {total_share}, target {kcal_daily}"
    )
    # Lunch must be the largest share (30/40/30 + snack pattern).
    assert shares["lunch"] == max(shares.values())


@pytest.mark.asyncio
async def test_weight_gain_spreads_intake_and_forces_snack() -> None:
    """weight_gain (nutrition expert 2026-06-16): intake spread over 4
    occasions with no slot >30 % of the day, so a high surplus target stays
    reachable by scaling a normal recipe within bounds instead of an uneatable
    giant plate. The snack slot is forced in even at the default meals_per_day."""
    targets = {**_valid_targets(), "goal": "weight_gain"}
    uc, _, _, layer2 = _pool_uc(targets=targets)
    plan = await uc(user_id=uuid4(), plan_type="day", seed=3)  # type: ignore[arg-type]

    assert plan.meals_per_day == 4, "weight_gain must force the snack occasion in"
    assert len(plan.days[0].meals) == 4
    shares = {mt: k for mt, k, _ in layer2.share_calls}
    ceiling = round(targets["kcal_max"] * 0.30) + 1
    assert max(shares.values()) <= ceiling, (
        f"weight_gain slot {shares} exceeds the 30% reachable ceiling {ceiling}"
    )
