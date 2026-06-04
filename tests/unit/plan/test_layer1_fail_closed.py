"""R6 fail-closed Layer 1 invariant tests.

NOVA policy (2026-06-03): nutrition-safety-critical macro columns MUST be
non-NULL for a recipe to enter the candidate set for a user with the matching
condition. Catalog rows with `sugar_g IS NULL` are no longer included for
diabetes_t2 users (etc).

These tests assert the SQL Layer 1 emits enforces the policy. We intercept
the SQL string by stubbing `AsyncSession.execute` and inspecting the rendered
query, so the test stays at the unit level (no DB required).
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


_PROFILE_DIABETES = {
    "region": "es",
    "allergies": [],
    "conditions": ["diabetes_t2"],
    "weight_kg": Decimal("70"),
}
_PROFILE_HYPERTENSION = {
    "region": "es",
    "allergies": [],
    "conditions": ["hypertension"],
    "weight_kg": Decimal("70"),
}
_PROFILE_HYPERCHOL = {
    "region": "es",
    "allergies": [],
    "conditions": ["hypercholesterolemia"],
    "weight_kg": Decimal("70"),
}
_PROFILE_CKD = {
    "region": "es",
    "allergies": [],
    "conditions": ["ckd"],
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
# Inline Layer 1 filters (sugar/sodium/sat_fat/protein) — must be IS NOT NULL.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diabetes_t2_inline_sugar_filter_excludes_nulls() -> None:
    cap = await _run(_PROFILE_DIABETES)
    assert "r.sugar_g IS NOT NULL AND r.sugar_g <= 15" in cap.sql, cap.sql
    # And the bias-include phrasing must NOT survive.
    assert "r.sugar_g IS NULL OR r.sugar_g <= 15" not in cap.sql


@pytest.mark.asyncio
async def test_hypertension_inline_sodium_filter_excludes_nulls() -> None:
    cap = await _run(_PROFILE_HYPERTENSION)
    assert "r.sodium_mg IS NOT NULL AND r.sodium_mg <= 600" in cap.sql, cap.sql
    assert "r.sodium_mg IS NULL OR r.sodium_mg <= 600" not in cap.sql


@pytest.mark.asyncio
async def test_hypercholesterolemia_inline_satfat_filter_excludes_nulls() -> None:
    cap = await _run(_PROFILE_HYPERCHOL)
    assert "r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= 5" in cap.sql, cap.sql
    assert "r.sat_fat_g IS NULL OR r.sat_fat_g <= 5" not in cap.sql


@pytest.mark.asyncio
async def test_ckd_inline_protein_filter_excludes_nulls() -> None:
    cap = await _run(_PROFILE_CKD)
    assert "r.protein_g IS NOT NULL AND r.protein_g <= :ckd_protein_cap" in cap.sql, cap.sql
    assert "r.protein_g IS NULL OR r.protein_g <= :ckd_protein_cap" not in cap.sql
    assert cap.params.get("ckd_protein_cap") is not None


# ---------------------------------------------------------------------------
# Condition gates (composed via the registry) must also be fail-closed for the
# columns flipped in R6.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diabetes_t2_gate_sugar_carbs_fail_closed() -> None:
    cap = await _run(_PROFILE_DIABETES)
    # From DiabetesT2Gate.contribute_sql — sugar/carbs flipped to IS NOT NULL.
    assert "r.sugar_g IS NOT NULL AND r.sugar_g <= :dt2_sugar_max" in cap.sql, cap.sql
    assert "r.carbs_g IS NOT NULL AND r.carbs_g <= :dt2_carbs_max" in cap.sql, cap.sql
    # Old COALESCE phrasing must not survive.
    assert "COALESCE(r.sugar_g, 0)" not in cap.sql
    assert "COALESCE(r.carbs_g, 0)" not in cap.sql


@pytest.mark.asyncio
async def test_hypertension_gate_sodium_fail_closed() -> None:
    cap = await _run(_PROFILE_HYPERTENSION)
    # HypertensionGate fragment — sodium_mg fail-closed.
    assert "r.sodium_mg IS NOT NULL AND r.sodium_mg <= :ht_sodium_max" in cap.sql, cap.sql
    assert "COALESCE(r.sodium_mg, 0)" not in cap.sql


@pytest.mark.asyncio
async def test_ckd_gate_sodium_protein_fail_closed() -> None:
    cap = await _run(_PROFILE_CKD)
    # CKDGate fragment — sodium + protein fail-closed.
    assert "r.sodium_mg IS NOT NULL AND r.sodium_mg <= :ckd_na_max" in cap.sql, cap.sql
    assert "r.protein_g IS NOT NULL AND r.protein_g <= :ckd_protein_max" in cap.sql, cap.sql
    assert "COALESCE(r.sodium_mg, 0)" not in cap.sql
    assert "COALESCE(r.protein_g, 0)" not in cap.sql
    # Potassium / phosphorus stay COALESCE(., 9999) — already biased safe.
    assert "COALESCE(r.potassium_mg, 9999)" in cap.sql
    assert "COALESCE(r.phosphorus_mg, 9999)" in cap.sql
