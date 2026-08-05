"""R6 fail-closed Layer 1 invariant tests.

NOVA policy (2026-06-03): nutrition-safety-critical macro columns MUST be
non-NULL for a recipe to enter the candidate set for a user with the matching
condition. Catalog rows with `sugar_g IS NULL` are no longer included for a
fatty_liver user (etc).

Scope (owner decision 2026-07-09, gates removed 2026-07-10): only three
in-scope conditions have gates — fatty_liver (nutrition-managed situation),
pregnancy and lactation (life stages). Out-of-scope medical gates
(diabetes_t2, hypertension, hypercholesterolemia, ckd, gout,
ischemic_heart_disease) were removed; celiac / lactose_intolerance are handled
via the `gluten` / `dairy` allergens, never as conditions.

Filters come from the registry (ConditionGate). Tests are agnostic about the
source; they only verify the fragment is present in the final WHERE clause.
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
    def all(self) -> list[tuple[UUID, ...]]:  # noqa: D401 — mimic sqlalchemy result
        return []


class _StubSession:
    """Minimal AsyncSession stand-in that captures the rendered SQL string."""

    def __init__(self) -> None:
        self.captured: _CapturedSQL | None = None

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _StubResult:
        # `stmt` is a TextClause; render its string form for inspection.
        self.captured = _CapturedSQL(sql=str(stmt), params=params)
        return _StubResult()


class _StubProfileReader:
    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile

    async def get_eligibility_profile(self, user_id: UUID) -> dict[str, Any]:
        return self._profile


_PROFILE_FATTY_LIVER = {
    "region": "es",
    "allergies": [],
    "conditions": ["fatty_liver"],
    "weight_kg": Decimal("70"),
}
_PROFILE_PREGNANCY = {
    "region": "es",
    "allergies": [],
    "conditions": ["pregnancy"],
    "weight_kg": Decimal("70"),
}
_PROFILE_LACTATION = {
    "region": "es",
    "allergies": [],
    "conditions": ["lactation"],
    "weight_kg": Decimal("70"),
}


async def _run(profile: dict[str, Any]) -> _CapturedSQL:
    session = _StubSession()
    use_case = Layer1Eligibility(
        session=session,  # type: ignore[arg-type] — duck-typed stub
        profile_reader=_StubProfileReader(profile),
    )
    await use_case(user_id=uuid4(), meal_time="lunch")
    assert session.captured is not None, "session.execute was never called"
    return session.captured


# ---------------------------------------------------------------------------
# Fail-closed filters — fragments come from the registry gates. The
# fatty_liver gate flips added_sugar_g / sat_fat_g to IS NOT NULL (R6): a
# catalog row missing either safety-critical macro is excluded, never admitted.
# The separate total-sugar ceiling IS bias-admit — it is a fructose-dose limit,
# not a free-sugar safety floor, and NULL total sugar must not shrink the pool.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fatty_liver_sugar_filter_excludes_nulls() -> None:
    # FattyLiverGate contributes this fragment via registry.
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "r.added_sugar_g IS NOT NULL AND r.added_sugar_g <= :fl_added_sugar_max" in cap.sql, cap.sql
    # The FREE-sugar filter is fail-closed: NULL added_sugar_g is excluded, and
    # must never be relaxed into a bias-admit form.
    assert "r.added_sugar_g IS NULL OR r.added_sugar_g <= " not in cap.sql
    assert cap.params.get("fl_added_sugar_max") == 8
    # The TOTAL-sugar clause is deliberately bias-admit (fructose-dose ceiling).
    assert "(r.sugar_g IS NULL OR r.sugar_g <= :fl_total_sugar_max)" in cap.sql
    assert cap.params.get("fl_total_sugar_max") == 30


@pytest.mark.asyncio
async def test_fatty_liver_satfat_filter_excludes_nulls() -> None:
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :fl_satfat_max" in cap.sql, cap.sql
    assert "r.sat_fat_g IS NULL OR r.sat_fat_g <= " not in cap.sql
    assert cap.params.get("fl_satfat_max") == 5


@pytest.mark.asyncio
async def test_fatty_liver_gate_sugar_satfat_fail_closed() -> None:
    cap = await _run(_PROFILE_FATTY_LIVER)
    # From FattyLiverGate.contribute_sql — sugar/sat_fat are IS NOT NULL.
    assert "r.added_sugar_g IS NOT NULL AND r.added_sugar_g <= :fl_added_sugar_max" in cap.sql, cap.sql
    assert "r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :fl_satfat_max" in cap.sql, cap.sql
    # Safety-critical macros must never be admitted via COALESCE-to-zero.
    assert "COALESCE(r.sugar_g, 0)" not in cap.sql
    assert "COALESCE(r.sat_fat_g, 0)" not in cap.sql


@pytest.mark.asyncio
async def test_fatty_liver_fiber_bias_admit() -> None:
    # Fiber is now bias-ADMIT (2026-08-03): 95% of catalog has NULL fiber_g;
    # fail-closed shrinks Bolivia+fatty_liver pool below 7-per-slot minimum.
    # NULL fiber_g passes through; confirmed low-fiber (< 3g) still excluded.
    # NOT refined_carbs/high_fructose tags provide fallback protection.
    cap = await _run(_PROFILE_FATTY_LIVER)
    assert "r.fiber_g IS NULL OR r.fiber_g >= :fl_fiber_min" in cap.sql, cap.sql
    assert "COALESCE(r.fiber_g, 0)" not in cap.sql  # old fail-closed must not be present
    assert cap.params.get("fl_fiber_min") == 3


# ---------------------------------------------------------------------------
# Life-stage gates (pregnancy / lactation) — the single pregnancy_safe flag.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pregnancy_gate_requires_pregnancy_safe() -> None:
    cap = await _run(_PROFILE_PREGNANCY)
    assert "r.pregnancy_safe = TRUE" in cap.sql, cap.sql


@pytest.mark.asyncio
async def test_lactation_gate_requires_pregnancy_safe() -> None:
    cap = await _run(_PROFILE_LACTATION)
    assert "r.pregnancy_safe = TRUE" in cap.sql, cap.sql
