"""Layer1 correctly applies disliked_ingredients filter in swap and plan creation.

Verifies:
- SQL contains disliked clause when profile has disliked_ingredients
- Disliked clause is absent when list is empty
- Fallback: when all candidates are disliked, Layer1 relaxes preference (never aborts for taste)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.plan.application.layer1_eligibility import Layer1Eligibility


@dataclass(slots=True)
class _CapturedSQL:
    sql: str
    params: dict[str, Any]


class _StubResult:
    def __init__(self, rows: list[tuple[UUID, ...]] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[tuple[UUID, ...]]:
        return self._rows


class _StubSession:
    def __init__(self, rows: list[tuple[UUID, ...]] | None = None) -> None:
        self.captured: list[_CapturedSQL] = []
        self._rows = rows or []

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _StubResult:
        self.captured.append(_CapturedSQL(sql=str(stmt), params=params))
        return _StubResult(self._rows)


class _StubProfileReader:
    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile

    async def get_eligibility_profile(self, user_id: UUID) -> dict[str, Any]:
        return self._profile


_BASE_PROFILE: dict[str, Any] = {
    "region": "latam",
    "allergies": [],
    "conditions": [],
    "weight_kg": Decimal("70"),
    "disliked_ingredients": [],
}


@pytest.mark.asyncio
async def test_disliked_clause_present_when_profile_has_dislikes() -> None:
    session = _StubSession()
    profile = {**_BASE_PROFILE, "disliked_ingredients": ["brócoli", "cebolla"]}
    layer1 = Layer1Eligibility(
        session=session,  # type: ignore[arg-type]
        profile_reader=_StubProfileReader(profile),  # type: ignore[arg-type]
    )
    await layer1(user_id=uuid4(), meal_time="lunch")

    assert session.captured, "Layer1 must execute at least one SQL query"
    last_sql = session.captured[-1]
    assert "disliked_patterns" in last_sql.params, "disliked_patterns param missing from SQL"
    patterns = last_sql.params["disliked_patterns"]
    assert "%brócoli%" in patterns or any("br" in p for p in patterns)
    assert "%cebolla%" in patterns or any("cebolla" in p for p in patterns)


@pytest.mark.asyncio
async def test_disliked_clause_absent_when_empty_list() -> None:
    session = _StubSession()
    profile = {**_BASE_PROFILE, "disliked_ingredients": []}
    layer1 = Layer1Eligibility(
        session=session,  # type: ignore[arg-type]
        profile_reader=_StubProfileReader(profile),  # type: ignore[arg-type]
    )
    await layer1(user_id=uuid4(), meal_time="lunch")

    for captured in session.captured:
        assert "disliked_patterns" not in captured.params, (
            "disliked_patterns must not appear when list is empty"
        )


@pytest.mark.asyncio
async def test_disliked_clause_absent_when_key_missing() -> None:
    """Profile without disliked_ingredients key (legacy profiles) must not crash."""
    session = _StubSession()
    profile = {k: v for k, v in _BASE_PROFILE.items() if k != "disliked_ingredients"}
    layer1 = Layer1Eligibility(
        session=session,  # type: ignore[arg-type]
        profile_reader=_StubProfileReader(profile),  # type: ignore[arg-type]
    )
    await layer1(user_id=uuid4(), meal_time="lunch")

    for captured in session.captured:
        assert "disliked_patterns" not in captured.params


@pytest.mark.asyncio
async def test_disliked_filter_relaxed_when_pool_would_be_empty() -> None:
    """PREFERENCE rule: when disliked filter empties the pool, Layer1 relaxes it.

    A swap must never abort for taste — only safety filters are hard-stops.
    The stub returns empty on the first (filtered) call, then a result on retry.
    """
    recipe_id = uuid4()

    call_count = 0

    class _TwoPassSession:
        captured: list[_CapturedSQL] = []

        async def execute(self, stmt: Any, params: dict[str, Any]) -> _StubResult:
            nonlocal call_count
            call_count += 1
            self.captured.append(_CapturedSQL(sql=str(stmt), params=params))
            # First call (with disliked filter) → empty; second (relaxed) → result
            if call_count == 1:
                return _StubResult([])
            return _StubResult([(recipe_id,)])

    session = _TwoPassSession()
    profile = {**_BASE_PROFILE, "disliked_ingredients": ["brócoli"]}
    layer1 = Layer1Eligibility(
        session=session,  # type: ignore[arg-type]
        profile_reader=_StubProfileReader(profile),  # type: ignore[arg-type]
    )
    result = await layer1(user_id=uuid4(), meal_time="lunch")

    assert recipe_id in result, "relaxed fallback must return the candidate"
    assert call_count == 2, "must retry without disliked filter when first pass is empty"
