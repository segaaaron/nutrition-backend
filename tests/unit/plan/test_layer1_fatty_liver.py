"""Layer 1 dispatch test — `fatty_liver` profile composes FattyLiverGate SQL.

Mirrors the pattern in `test_layer1_fail_closed.py`: stub `AsyncSession` to
capture the rendered SQL string, then assert the NAFLD filters were composed
via the ConditionGate registry. Confirms also that profiles WITHOUT
`fatty_liver` do not receive the filters.
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
    def all(self) -> list[tuple[UUID, ...]]:
        return []


class _StubSession:
    def __init__(self) -> None:
        self.captured: _CapturedSQL | None = None

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _StubResult:
        self.captured = _CapturedSQL(sql=str(stmt), params=params)
        return _StubResult()


class _StubProfileReader:
    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile

    async def get_eligibility_profile(self, user_id: UUID) -> dict[str, Any]:
        return self._profile


_PROFILE_FATTY_LIVER = {
    "region": "latam",
    "allergies": [],
    "conditions": ["fatty_liver"],
    "weight_kg": Decimal("75"),
}
_PROFILE_NO_CONDITIONS = {
    "region": "latam",
    "allergies": [],
    "conditions": [],
    "weight_kg": Decimal("75"),
}


async def _run(profile: dict[str, Any]) -> _CapturedSQL:
    session = _StubSession()
    use_case = Layer1Eligibility(
        session=session,  # type: ignore[arg-type]
        profile_reader=_StubProfileReader(profile),
    )
    await use_case(user_id=uuid4(), meal_time="lunch")
    assert session.captured is not None
    return session.captured


@pytest.mark.asyncio
async def test_fatty_liver_applies_sugar_filter() -> None:
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "r.sugar_g IS NOT NULL AND r.sugar_g <= :fl_sugar_max" in cap.sql, cap.sql
    assert cap.params.get("fl_sugar_max") == 8


@pytest.mark.asyncio
async def test_fatty_liver_applies_satfat_filter() -> None:
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :fl_satfat_max" in cap.sql, cap.sql
    assert cap.params.get("fl_satfat_max") == 5


@pytest.mark.asyncio
async def test_fatty_liver_applies_fiber_floor() -> None:
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "COALESCE(r.fiber_g, 0) >= :fl_fiber_min" in cap.sql, cap.sql
    assert cap.params.get("fl_fiber_min") == 3


@pytest.mark.asyncio
async def test_fatty_liver_excludes_refined_carbs_tag() -> None:
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "ARRAY['refined_carbs','high_fructose']::text[]" in cap.sql, cap.sql


@pytest.mark.asyncio
async def test_no_conditions_profile_does_not_apply_fatty_liver_filters() -> None:
    cap = await _run(_PROFILE_NO_CONDITIONS)
    assert ":fl_sugar_max" not in cap.sql
    assert ":fl_satfat_max" not in cap.sql
    assert ":fl_fiber_min" not in cap.sql
    assert "fl_sugar_max" not in cap.params
