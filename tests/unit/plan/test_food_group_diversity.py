"""Food group diversity validation — unit tests (WHO 2023 + USDA MyPlate).

Covers:
  1. plan.day_no_protein_source  — no meal in the day has scaled protein_g ≥ 20g
  2. No warning when ≥1 meal has protein_g ≥ 20g
  3. plan.week_legumes_below_who — legume servings < 3/week across the plan
  4. plan.week_fish_below_who    — fish/omega3 servings < 2/week across the plan
  5. No weekly warnings when targets are met

Architecture notes:
  - Weekly legume count: embedding_cache[rid][3] contains "legumes" tag.
  - Weekly fish count:   embedding_cache[rid][2] (omega3_mg) ≥ 150.
  - Per-day protein:     m.protein_g (scaled) set from fetch_recipe_macros.
  - All checks are warn-only — never raise BusinessRuleViolation.
  - structlog.testing.capture_logs used (not caplog) because the module
    uses structlog which bypasses stdlib logging in the test environment.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from app.core.event_bus import EventBus
from app.plan.application.create_plan import CreatePlan
from app.plan.domain.entities import Plan


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _ProfileCtxNoOp:
    async def get_ranking_context(self, user_id: UUID) -> dict:
        return {}


class _Layer4NoOp:
    async def __call__(self, **_: Any) -> dict:
        return {}


class _Layer2PassThrough:
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
        return [(rid, 1.0) for rid in candidate_ids if rid not in forbidden_ids]


def _make_layer3(
    *,
    omega3_mg: int | None = None,
    tags: list[str] | None = None,
) -> Any:
    """Layer3 stub that populates embedding_cache with controlled features."""

    class _Layer3Stub:
        profile_ctx = _ProfileCtxNoOp()

        async def __call__(
            self,
            *,
            user_id: UUID,
            candidate_ids: list[UUID],
            embedding_cache: dict | None = None,
            **_: Any,
        ) -> list[tuple[UUID, float]]:
            if embedding_cache is not None:
                for rid in candidate_ids:
                    if rid not in embedding_cache:
                        # Tuple: (regions, prep_min, omega3_mg, tags, gl, folate_ug, sugar_g, embedding)
                        embedding_cache[rid] = (
                            ["latam"],           # 0 regions
                            20,                  # 1 prep_min
                            omega3_mg,           # 2 omega3_mg
                            tags or [],          # 3 tags
                            None,                # 4 gl
                            None,                # 5 folate_ug
                            None,                # 6 sugar_g
                            [0.1] * 10,          # 7 embedding (stub)
                        )
            return [(rid, 1.0) for rid in candidate_ids]

    return _Layer3Stub()


def _build_uc(
    *,
    recipe_ids: list[UUID],
    macros_by_id: dict[UUID, tuple],
    targets: dict[str, Any],
    omega3_mg: int | None = None,
    tags: list[str] | None = None,
) -> tuple[CreatePlan, Any]:
    class _Layer1Fixed:
        async def __call__(self, *, user_id: UUID, meal_time: str) -> list[UUID]:
            return recipe_ids

    class _StubPlans:
        def __init__(self) -> None:
            self.saved: list[Any] = []

        async def acquire_user_lock(self, user_id: UUID) -> None: ...
        async def archive_active(self, user_id: UUID) -> int: return 0
        async def count_recent_recipe_occurrences(self, user_id: UUID, *, days: int = 30) -> dict: return {}
        async def recipe_completion_rates(self, user_id: UUID, *, days: int = 90) -> dict: return {}
        async def save(self, plan: Any) -> Any:
            self.saved.append(plan)
            return plan
        async def save_seed(self, plan_id: UUID, seed: int) -> None: ...

        async def fetch_recipe_macros(
            self, recipe_ids: list[UUID]
        ) -> dict[UUID, tuple]:
            return {rid: macros_by_id[rid] for rid in recipe_ids if rid in macros_by_id}

    plans = _StubPlans()

    class _UserCtx:
        async def get_user_targets(self, user_id: UUID) -> dict:
            return targets
        async def get_user_profile_snapshot(self, user_id: UUID) -> dict:
            return {"locale": "es"}

    uc = CreatePlan(
        plans=plans,  # type: ignore[arg-type]
        layer1=_Layer1Fixed(),  # type: ignore[arg-type]
        layer2=_Layer2PassThrough(),  # type: ignore[arg-type]
        layer3=_make_layer3(omega3_mg=omega3_mg, tags=tags),  # type: ignore[arg-type]
        layer4=_Layer4NoOp(),  # type: ignore[arg-type]
        user_ctx=_UserCtx(),  # type: ignore[arg-type]
        bus=EventBus(),
    )
    return uc, plans


def _targets(kcal: int = 2000, protein: int = 120) -> dict[str, Any]:
    return {"kcal_max": kcal, "protein_g": protein, "water_ml": 2500}


def _events(logs: list[dict]) -> list[str]:
    """Extract structlog event keys from a capture_logs list."""
    return [r.get("event", "") for r in logs]


# ---------------------------------------------------------------------------
# 1. Per-day protein source — warns when no meal has protein_g ≥ 20g
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_day_no_protein_source_warns() -> None:
    """All meals stay below 20g protein → plan.day_no_protein_source warning.

    Recipe: kcal=400, protein=8. _MAX_SCALE=2.0 → max protein per meal
    = round(8 × 2.0) = 16g < 20g threshold in every slot.
    """
    rid = uuid4()
    uc, _ = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (400, 8, 60, 12, None, None, 5, 200)},
        targets=_targets(protein=100),
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="day")  # type: ignore[arg-type]

    assert plan is not None
    assert "plan.day_no_protein_source" in _events(logs)


@pytest.mark.asyncio
async def test_day_protein_source_present_no_warn() -> None:
    """At least one meal has protein_g = 30 (≥20g) → no protein-source warning."""
    rid = uuid4()
    uc, _ = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 30, 50, 15, None, None, 5, 300)},
        targets=_targets(protein=120),
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="day")  # type: ignore[arg-type]

    assert plan is not None
    assert "plan.day_no_protein_source" not in _events(logs)


@pytest.mark.asyncio
async def test_day_no_protein_source_does_not_raise() -> None:
    """protein source absence is warn-only — plan must still be saved."""
    rid = uuid4()
    uc, plans = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (400, 5, 70, 8, None, None, 4, 150)},
        targets=_targets(protein=100),
    )
    plan: Plan = await uc(user_id=uuid4(), plan_type="day")  # type: ignore[arg-type]
    assert len(plans.saved) == 1
    assert plan.id == plans.saved[0].id


# ---------------------------------------------------------------------------
# 2. Weekly legume diversity — warns when legumes < 3/week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_week_no_legumes_warns() -> None:
    """No recipe has legumes tag → plan.week_legumes_below_who warning."""
    rid = uuid4()
    uc, _ = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 30, 50, 15, None, None, 6, 300)},
        targets=_targets(),
        tags=[],  # no legumes tag
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert plan is not None
    assert "plan.week_legumes_below_who" in _events(logs)


@pytest.mark.asyncio
async def test_week_legumes_met_no_warn() -> None:
    """All recipes tagged legumes → ≥3 legume servings/week → no warning.

    A week plan with 3 meals/day = 21 meals all tagged legumes → 21/week >> 3.
    """
    rid = uuid4()
    uc, _ = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 25, 60, 10, None, None, 8, 400)},
        targets=_targets(),
        tags=["legumes", "high-protein"],
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert plan is not None
    assert "plan.week_legumes_below_who" not in _events(logs)


@pytest.mark.asyncio
async def test_week_legumes_warn_does_not_raise() -> None:
    """Legume deficit is warn-only — plan must be saved."""
    rid = uuid4()
    uc, plans = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 30, 50, 15, None, None, 5, 300)},
        targets=_targets(),
        tags=[],
    )
    plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]
    assert len(plans.saved) == 1


# ---------------------------------------------------------------------------
# 3. Weekly fish diversity — warns when omega3 servings < 2/week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_week_no_fish_warns() -> None:
    """No recipe has omega3_mg ≥ 150 → plan.week_fish_below_who warning."""
    rid = uuid4()
    uc, _ = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 30, 50, 15, None, None, 5, 300)},
        targets=_targets(),
        omega3_mg=0,  # no omega3
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert plan is not None
    assert "plan.week_fish_below_who" in _events(logs)


@pytest.mark.asyncio
async def test_week_fish_met_no_warn() -> None:
    """All recipes have omega3_mg=200 (≥150) → ≥2 fish/week → no warning."""
    rid = uuid4()
    uc, _ = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 35, 40, 18, None, None, 5, 250)},
        targets=_targets(),
        omega3_mg=200,
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert plan is not None
    assert "plan.week_fish_below_who" not in _events(logs)


@pytest.mark.asyncio
async def test_week_fish_warn_does_not_raise() -> None:
    """Fish deficit is warn-only — plan must be saved."""
    rid = uuid4()
    uc, plans = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 30, 50, 15, None, None, 5, 300)},
        targets=_targets(),
        omega3_mg=None,
    )
    plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]
    assert len(plans.saved) == 1


# ---------------------------------------------------------------------------
# 4. Day plan: weekly checks use total_days=1 → 1/7 week → always warns
#    (day plan can't hit 3 legumes/week or 2 fish/week in 1 day — expected)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_day_plan_always_warns_weekly_diversity() -> None:
    """A single-day plan (total_days=1) can never reach weekly targets.
    Both weekly warnings fire; the plan is still saved. This is by design:
    weekly diversity is measured at plan scope, not imposed per-day.
    """
    rid = uuid4()
    uc, plans = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (500, 30, 50, 15, None, None, 5, 300)},
        targets=_targets(),
        tags=[],
        omega3_mg=None,
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="day")  # type: ignore[arg-type]

    assert len(plans.saved) == 1
    events = _events(logs)
    assert "plan.week_legumes_below_who" in events
    assert "plan.week_fish_below_who" in events


# ---------------------------------------------------------------------------
# 5. All warnings are additive — none interfere with each other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_diversity_warnings_fire_together() -> None:
    """Worst-case plan: protein_g=5, no legumes, no fish → all 3 warnings fire."""
    rid = uuid4()
    uc, plans = _build_uc(
        recipe_ids=[rid],
        macros_by_id={rid: (400, 5, 70, 8, None, None, 4, 150)},
        targets=_targets(protein=100),
        tags=[],
        omega3_mg=0,
    )
    with capture_logs() as logs:
        plan: Plan = await uc(user_id=uuid4(), plan_type="week")  # type: ignore[arg-type]

    assert len(plans.saved) == 1
    events = _events(logs)
    assert "plan.day_no_protein_source" in events
    assert "plan.week_legumes_below_who" in events
    assert "plan.week_fish_below_who" in events
