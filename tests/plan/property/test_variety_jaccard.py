"""Property-based tests for H1.5 Jaccard variety penalty.

200 hypothesis examples per property. Decimal-only assertions. No DB.
A sync fake ``RecentRecipesReader`` is used; its methods are ``async``
to honour the Protocol.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.context import MacroTargets, PlanGenContext, RecipeView
from app.plan.domain.ranking_signals.variety_jaccard import (
    JaccardVarietyPenalty,
)


_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    derandomize=False,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FakeRecentReader:
    tags: frozenset[str] = frozenset()
    classes: frozenset[str] = frozenset()
    used_ids: frozenset[UUID] = field(default_factory=frozenset)

    async def tags_used_14d(self, user_id: UUID) -> frozenset[str]:
        return self.tags

    async def ingredient_classes_used_14d(
        self, user_id: UUID
    ) -> frozenset[str]:
        return self.classes

    async def recipe_ids_used_7d(self, user_id: UUID) -> frozenset[UUID]:
        return self.used_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx() -> PlanGenContext:
    return PlanGenContext(
        user_id=uuid4(),
        targets=MacroTargets(
            kcal=Decimal("2000"),
            protein_g=Decimal("120"),
            carbs_g=Decimal("220"),
            fat_g=Decimal("66"),
        ),
    )


def _recipe(tags: tuple[str, ...], rid: UUID | None = None) -> RecipeView:
    return RecipeView(
        id=rid if rid is not None else uuid4(),
        kcal=Decimal("500"),
        protein_g=Decimal("30"),
        carbs_g=Decimal("55"),
        fat_g=Decimal("16"),
        fiber_g=Decimal("8"),
        sodium_mg=400,
        sugar_g=Decimal("5"),
        sat_fat_g=Decimal("3"),
        gi=55,
        tags=tags,
        allergens=(),
        meal_time="lunch",
        prep_min=25,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.new_event_loop().run_until_complete(coro)


_token = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=6,
)
_tag_set = st.frozensets(_token, min_size=0, max_size=8)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@_SETTINGS
@given(cand=_tag_set, recent_t=_tag_set, recent_c=_tag_set)
def test_variety_bounded(
    cand: frozenset[str],
    recent_t: frozenset[str],
    recent_c: frozenset[str],
) -> None:
    reader = FakeRecentReader(tags=recent_t, classes=recent_c)
    sig = JaccardVarietyPenalty(reader=reader)
    recipe = _recipe(tuple(cand))
    score = _run(sig.score(recipe, _ctx()))
    assert Decimal("0") <= score <= Decimal("1")


@_SETTINGS
@given(cand=_tag_set, recent=_tag_set)
def test_variety_orthogonal_disjoint_max(
    cand: frozenset[str], recent: frozenset[str]
) -> None:
    """Disjoint non-empty sets → Jaccard = 0 → variety = 1."""
    disjoint_recent = frozenset(f"R_{t}" for t in recent)
    if not cand or not disjoint_recent:
        return  # edge cases covered by other props
    reader = FakeRecentReader(tags=disjoint_recent, classes=frozenset())
    sig = JaccardVarietyPenalty(reader=reader)
    recipe = _recipe(tuple(cand))
    score = _run(sig.score(recipe, _ctx()))
    assert score == Decimal("1.0000")


@_SETTINGS
@given(s=_tag_set)
def test_variety_identical_zero(s: frozenset[str]) -> None:
    """candidate_set == recent_set (non-empty) → Jaccard = 1 → variety = 0."""
    if not s:
        return
    reader = FakeRecentReader(tags=s, classes=frozenset())
    sig = JaccardVarietyPenalty(reader=reader)
    recipe = _recipe(tuple(s))
    score = _run(sig.score(recipe, _ctx()))
    assert score == Decimal("0.0000")


@_SETTINGS
@given(
    cand=_tag_set,
    recent_t=_tag_set,
    recent_c=_tag_set,
)
def test_hard_7d_cap(
    cand: frozenset[str],
    recent_t: frozenset[str],
    recent_c: frozenset[str],
) -> None:
    """Recipe id in used_7d → score == 0 regardless of tag overlap."""
    rid = uuid4()
    reader = FakeRecentReader(
        tags=recent_t,
        classes=recent_c,
        used_ids=frozenset({rid}),
    )
    sig = JaccardVarietyPenalty(reader=reader)
    recipe = _recipe(tuple(cand), rid=rid)
    score = _run(sig.score(recipe, _ctx()))
    assert score == Decimal("0")


@_SETTINGS
@given(a=_tag_set, b=_tag_set)
def test_jaccard_symmetric(
    a: frozenset[str], b: frozenset[str]
) -> None:
    """Swapping candidate and recent yields same score (no hard cap)."""
    # Skip cases where the candidate side would be empty under either
    # ordering — the spec returns the neutral 0.5 there for safety,
    # so symmetry holds trivially but is uninteresting.
    if not a or not b:
        return
    reader_ab = FakeRecentReader(tags=b, classes=frozenset())
    reader_ba = FakeRecentReader(tags=a, classes=frozenset())
    sig_ab = JaccardVarietyPenalty(reader=reader_ab)
    sig_ba = JaccardVarietyPenalty(reader=reader_ba)
    score_ab = _run(sig_ab.score(_recipe(tuple(a)), _ctx()))
    score_ba = _run(sig_ba.score(_recipe(tuple(b)), _ctx()))
    assert score_ab == score_ba


def test_empty_union_returns_neutral() -> None:
    reader = FakeRecentReader()
    sig = JaccardVarietyPenalty(reader=reader)
    recipe = _recipe(())
    score = _run(sig.score(recipe, _ctx()))
    assert score == Decimal("0.5")


def test_empty_candidate_nonempty_recent_returns_neutral() -> None:
    reader = FakeRecentReader(tags=frozenset({"oats", "berries"}))
    sig = JaccardVarietyPenalty(reader=reader)
    recipe = _recipe(())
    score = _run(sig.score(recipe, _ctx()))
    assert score == Decimal("0.5")
