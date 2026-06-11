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
    ) -> list[tuple[UUID, float]]:
        return []


class _Layer3Empty:
    async def __call__(
        self,
        *,
        user_id: UUID,
        candidate_ids: list[UUID],
        meal_time: str,
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
