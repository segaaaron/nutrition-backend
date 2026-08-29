"""Patrón #5 — invariant: a grocery list whose source plan has meals
MUST persist at least one item.

The aggregation query in ``GenerateGroceryList`` can legitimately yield
zero rows when ``recipe_components`` is empty for every chosen recipe
(catalog corruption / seeds in flux). Previously the use case wrote a
``grocery_lists`` row with ZERO ``grocery_items`` to disk, producing
useless empty grocery surfaces in the iOS app. The fix raises
``BusinessRuleViolation`` so the outer session rolls back, leaving the
prior grocery list intact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.errors import BusinessRuleViolation
from app.grocery.domain import GroceryList
from app.grocery.use_cases import GenerateGroceryList


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None, first: Any = None) -> None:
        self._rows = rows or []
        self._first = first

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> Any:
        return self._first


class _FakeSession:
    """In-memory async session emulating the 3 SQL calls the use case
    issues: the (deprecated) join-foods query, the components aggregate,
    and the post-mutation ``plan_meals`` check + DELETE.
    """

    def __init__(
        self,
        *,
        components_rows: list[dict[str, Any]],
        plan_has_meals: bool,
    ) -> None:
        self._components_rows = components_rows
        self._plan_has_meals = plan_has_meals
        self.executed_sql: list[str] = []

    async def execute(self, stmt, params=None):  # type: ignore[override]
        sql = str(stmt)
        self.executed_sql.append(sql)
        # Detect the combined UNION query (new) or legacy SUM(rc.amount_g) (old).
        # The UNION query contains "UNION ALL" + "plan_meal_items"; the legacy had
        # "SUM(rc.amount_g)" at the top level. Both are the "components aggregate" call.
        if "UNION ALL" in sql or "SUM(rc.amount_g)" in sql:
            return _FakeResult(rows=self._components_rows)
        if "DELETE FROM grocery_items" in sql:
            return _FakeResult()
        if "FROM plan_meals pm" in sql and "SELECT 1" in sql:
            return _FakeResult(first=(1,) if self._plan_has_meals else None)
        # Original "join f on f.id" placeholder query — returns nothing
        # (use case re-issues a corrected query and uses THAT result).
        return _FakeResult(rows=[])


class _FakeRepo:
    def __init__(self) -> None:
        self.list_id = uuid4()
        self.items_inserted: list[Any] = []

    async def get_or_create_list(self, plan_id: UUID) -> GroceryList:
        return GroceryList(
            id=self.list_id,
            plan_id=plan_id,
            generated_at=datetime.now(UTC),
            items=[],
        )

    async def bulk_insert_items(self, items) -> None:
        self.items_inserted.extend(items)


@pytest.mark.asyncio
async def test_happy_path_plan_with_meals_and_components_persists_items() -> None:
    """Sanity: when components yield rows, the list is populated and the
    invariant check is short-circuited (no extra ``plan_meals`` probe).
    """
    rows = [{"name": "chicken breast", "total_g": 500.0}]
    session = _FakeSession(components_rows=rows, plan_has_meals=True)
    uc = GenerateGroceryList(session=session, repo=_FakeRepo())

    plan_id = uuid4()
    out = await uc(plan_id=plan_id)

    assert len(out.items) == 1
    assert out.items[0].name == "chicken breast"
    # Post-mutation probe NOT executed (items list non-empty).
    assert not any("FROM plan_meals pm" in s and "SELECT 1" in s for s in session.executed_sql)


@pytest.mark.asyncio
async def test_invariant_violated_plan_with_meals_but_zero_items_raises() -> None:
    """Plan has meals → components query returned nothing → invariant fails.

    The outer session.rollback() (driven by the FastAPI dependency in
    real flows) leaves the previous list intact.
    """
    session = _FakeSession(components_rows=[], plan_has_meals=True)
    uc = GenerateGroceryList(session=session, repo=_FakeRepo())

    with pytest.raises(BusinessRuleViolation) as excinfo:
        await uc(plan_id=uuid4())
    assert "grocery_generation_yielded_no_items" in str(excinfo.value)


@pytest.mark.asyncio
async def test_invariant_skipped_when_plan_has_no_meals() -> None:
    """Edge case: an empty plan (no plan_meals at all) is NOT a violation
    of THIS invariant — it's a violation of the plan-generation
    invariant, caught at write time elsewhere. The grocery use case
    must not double-flag it.
    """
    session = _FakeSession(components_rows=[], plan_has_meals=False)
    uc = GenerateGroceryList(session=session, repo=_FakeRepo())

    out = await uc(plan_id=uuid4())
    assert out.items == []
