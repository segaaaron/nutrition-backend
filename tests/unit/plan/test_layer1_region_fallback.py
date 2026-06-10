"""Layer 1 region fallback (owner decision 2026-06-10).

Region is a cultural preference, not a safety filter. When the user's market
yields ZERO candidates after allergen + condition gates, Layer 1 retries the
same query across the whole catalog — with every safety clause intact and
only the region overlap dropped. If the first query yields candidates, no
fallback query is issued.
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
    def __init__(self, ids: list[UUID]) -> None:
        self._ids = ids

    def all(self) -> list[tuple[UUID]]:
        return [(i,) for i in self._ids]


class _StubSession:
    """Captures every executed query; returns scripted results in order."""

    def __init__(self, results: list[list[UUID]]) -> None:
        self.captured: list[_CapturedSQL] = []
        self._results = results

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _StubResult:
        self.captured.append(_CapturedSQL(sql=str(stmt), params=params))
        return _StubResult(self._results[len(self.captured) - 1])


class _StubProfileReader:
    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile

    async def get_eligibility_profile(self, user_id: UUID) -> dict[str, Any]:
        return self._profile


_PROFILE_FATTY_LIVER_LATAM = {
    "region": "latam",
    "allergies": ["dairy"],
    "conditions": ["fatty_liver"],
    "weight_kg": Decimal("97"),
}

_REGION_CLAUSE = "r.regions && CAST(:regions AS char(5)[])"


def _uc(session: _StubSession) -> Layer1Eligibility:
    return Layer1Eligibility(
        session=session,  # type: ignore[arg-type]
        profile_reader=_StubProfileReader(_PROFILE_FATTY_LIVER_LATAM),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_no_fallback_when_region_has_candidates() -> None:
    rid = uuid4()
    session = _StubSession(results=[[rid]])

    ids = await _uc(session)(user_id=uuid4(), meal_time="lunch")

    assert ids == [rid]
    assert len(session.captured) == 1
    assert _REGION_CLAUSE in session.captured[0].sql


@pytest.mark.asyncio
async def test_fallback_drops_region_but_keeps_safety_clauses() -> None:
    rid = uuid4()
    session = _StubSession(results=[[], [rid]])

    ids = await _uc(session)(user_id=uuid4(), meal_time="lunch")

    assert ids == [rid]
    assert len(session.captured) == 2
    first, second = session.captured
    assert _REGION_CLAUSE in first.sql
    assert _REGION_CLAUSE not in second.sql
    # Safety filters MUST survive the fallback identically.
    assert "allergens" in second.sql
    assert "contraindicated_conditions" in second.sql
    # fatty_liver gate clauses (sugar/sat_fat caps + fiber floor).
    assert "sugar_g" in second.sql
    assert "sat_fat_g" in second.sql
    assert "fiber_g" in second.sql
    # Bound params unchanged (same allergies/conditions).
    assert second.params["allergies"] == ["dairy"]


@pytest.mark.asyncio
async def test_fallback_empty_returns_empty() -> None:
    session = _StubSession(results=[[], []])

    ids = await _uc(session)(user_id=uuid4(), meal_time="dinner")

    assert ids == []
    assert len(session.captured) == 2
