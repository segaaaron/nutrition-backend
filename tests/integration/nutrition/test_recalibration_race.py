"""Sprint 3 D5 — Recalibration race condition tests (integration-tier).

Quarantined here because race semantics genuinely belong on real Postgres
+ pg_advisory_xact_lock + partial unique index. The asyncio-fake
reproductions below are best-effort approximations: they exercise the
IntegrityError downgrade path and lock-serialisation path of
``RecalibrateGoals`` without spinning Docker, but they are NOT a proof
of the same behaviour under real concurrent DB sessions.

Two behaviours under test:

1. If two writers somehow reach the INSERT step concurrently (e.g.
   one session bypassed the advisory lock), the second one sees the
   partial unique index violation, the IntegrityError is caught, and
   the use case returns ``RecalibrationSkipped("concurrent_recalibration")``.

2. ``asyncio.gather`` of two recalibrations against a serialising fake
   never deadlocks and yields exactly one active row at the end.

The lock-ordering assertion (lock acquired before any read) lives in
``tests/unit/nutrition/test_recalibration_race.py`` — that one is a
pure sequence check, no concurrency.

Fixture design notes (kept here so future maintainers do NOT regress):

Profile: weight 80 kg, height 175 cm, age 30, male → BMR ≈ 1749 kcal.
Current goals: tdee_current=2200, valid_from = now - 30d (clear of the
14d cooldown). Goal "maintain" so the athlete-bulk guard is irrelevant.

Tracking window (14 daily samples):
- weights: 80.0, 79.7, 79.5, 79.2, 79.0, 78.8, 78.5, 78.3, 78.1, 77.9,
  77.7, 77.5, 77.3, 77.1  (≈ −0.22 kg/day, ≈ −2.9 kg over 14d)
- intake: 1500 kcal/d × 14

Algorithm walk-through (must all PASS, otherwise we early-skip and the
IntegrityError path is dead):
- len(weights)=14 ≥ MIN_WEIGHT_POINTS=7 ✓
- len(kcal_in)=14 ≥ MIN_DAYS//2=7 ✓
- days_since=30 ≥ COOLDOWN_DAYS=14 ✓
- raw_mean=1500; BMI≈26.1 → overweight bucket → corrected_mean=1800
- intake floor: 1800 ≥ 0.5×1749=874.5 ✓ (no IntakeBelowPhysiologicalFloor)
- expected_kg_per_day = (1500−2200)/7700 ≈ −0.0909  → |·| ≥ 1e-4 ✓
- slope after winsorise+MAD ≈ −0.19 to −0.21
- delta_ratio ≈ slope/expected ≈ 2.1 → |2.1−1|=1.1 > 0.5 ✓ TRIGGER
- goal="maintain" (not "muscle_gain") → no athlete_bulk skip
=> recalibrate() returns RecalibrationResult, we proceed to
   expire_current_and_insert and the test's repo can raise IntegrityError
   or run the gather race.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.event_bus import EventBus
from app.nutrition.application.use_cases import RecalibrateGoals
from app.nutrition.domain.recalibration import (
    RecalibrationResult,
    RecalibrationSkipped,
)
from app.nutrition.domain.state_machine import NutritionalGoals

# Module-level integration marker: race semantics live on real DB.
# Excluded from default `pytest tests/unit` runs and from mutation testing.
pytestmark = pytest.mark.integration


# --- Tunables aligned with the fixture math documented at module top. ---
_TDEE_CURRENT = 2200
_BMR_PLACEHOLDER = 1749  # matches Mifflin output for the chosen biometrics
_KCAL_IN_DAILY = 1500
_WEIGHT_SERIES: list[tuple[int, float]] = [
    (0, 80.0),
    (1, 79.7),
    (2, 79.5),
    (3, 79.2),
    (4, 79.0),
    (5, 78.8),
    (6, 78.5),
    (7, 78.3),
    (8, 78.1),
    (9, 77.9),
    (10, 77.7),
    (11, 77.5),
    (12, 77.3),
    (13, 77.1),
]
_BIO = {
    "weight_kg": Decimal("80"),
    "height_cm": Decimal("175"),
    "age": 30,
    "sex": "male",
    "goal": "maintain",
    "activity_level": "moderately_active",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_goals(user_id: UUID, valid_from: datetime | None = None) -> NutritionalGoals:
    """Onboarding-shaped goals row with tdee_current=2200 so the delta ratio
    against 1500 kcal/d intake breaches the 50% threshold (see module doc)."""
    return NutritionalGoals.new(
        user_id=user_id,
        kcal_min=2100,
        kcal_max=2300,
        protein_g=140,
        carbs_g=260,
        fat_g=75,
        water_ml=2500,
        bmr=_BMR_PLACEHOLDER,
        tdee=_TDEE_CURRENT,
        activity_factor=Decimal("1.55"),
        reason="onboarding",
        valid_from=valid_from or (_now() - timedelta(days=30)),
    )


class _FakeProfileReader:
    def __init__(self, bio: dict | None) -> None:
        self._bio = bio

    async def biometrics(self, user_id: UUID) -> dict | None:
        return self._bio


class _FakeTrackingReader:
    def __init__(self) -> None:
        self.weights = list(_WEIGHT_SERIES)
        self.kcal_in = [_KCAL_IN_DAILY] * 14

    async def weight_series_14d(self, u: UUID) -> list[tuple[int, float]]:
        return self.weights

    async def kcal_in_14d(self, u: UUID) -> list[int]:
        return self.kcal_in


@dataclass
class _FakeGoalsRepo:
    user_id: UUID
    current: NutritionalGoals | None
    raise_integrity_on_insert: bool = False
    lock_calls: list[UUID] = field(default_factory=list)
    call_order: list[str] = field(default_factory=list)

    async def acquire_user_lock(self, user_id: UUID) -> None:
        self.lock_calls.append(user_id)
        self.call_order.append("lock")

    async def get_current(self, user_id: UUID):
        self.call_order.append("get_current")
        return self.current

    async def list_history(self, user_id: UUID, limit: int):
        return []

    async def expire_current_and_insert(self, user_id: UUID, new_goals):
        self.call_order.append("insert")
        if self.raise_integrity_on_insert:
            # Mimic Postgres unique-violation surfaced by SQLAlchemy.
            raise IntegrityError("INSERT ...", params={}, orig=Exception("one_current_goals"))
        self.current = new_goals
        return new_goals


class _NoopBus(EventBus):
    async def publish(self, *_a, **_kw):  # type: ignore[override]
        return None


async def test_integrity_error_downgraded_to_skip():
    """Defence-in-depth: if a concurrent INSERT wins the race the losing
    transaction returns a clean RecalibrationSkipped rather than raising
    a 500-class error. Fixtures crafted so recalibrate() returns a
    RecalibrationResult (not an early skip) — otherwise insert is never
    called and the IntegrityError catch is unreachable."""
    user_id = uuid4()
    repo = _FakeGoalsRepo(
        user_id=user_id,
        current=_make_goals(user_id),
        raise_integrity_on_insert=True,
    )
    uc = RecalibrateGoals(
        profile_reader=_FakeProfileReader(_BIO),
        tracking_reader=_FakeTrackingReader(),
        goals_repo=repo,
        bus=_NoopBus(),
    )

    result = await uc(user_id=user_id)

    assert "insert" in repo.call_order, (
        "fixture regression: recalibrate() early-skipped before reaching "
        "expire_current_and_insert; IntegrityError path was never exercised"
    )
    assert isinstance(result, RecalibrationSkipped)
    assert result.reason == "concurrent_recalibration"


async def test_parallel_recalibrations_one_winner():
    """``asyncio.gather`` two recalibrations against a single fake repo.

    The fake serialises behind an ``asyncio.Lock`` inside
    ``acquire_user_lock`` (mirroring what pg_advisory_xact_lock does at
    the DB level). After the first commit, the second writer reads the
    freshly-inserted goal as ``current`` (so days_since=0 → cooldown
    skip), or hits the unique index path. Either way: no exception
    propagated, no deadlock.

    Deadlock guard (regression fix): the lock MUST be released on every
    exit path from the protected region, not just on the
    expire_current_and_insert success path. Earlier versions released
    only inside expire_current_and_insert; whenever recalibrate() took
    an early-skip branch the lock was held forever and the second call
    awaited indefinitely. We now wrap the entire use case invocation
    in try/finally so the asyncio.Lock release matches the real
    pg_advisory_xact_lock's auto-release-on-commit-or-rollback semantics.
    """
    user_id = uuid4()
    initial = _make_goals(user_id)

    class _SerialisingRepo(_FakeGoalsRepo):
        def __init__(self, **kw):
            super().__init__(**kw)
            self._lock = asyncio.Lock()
            self._lock_held: bool = False

        async def acquire_user_lock(self, uid):
            await self._lock.acquire()
            self._lock_held = True
            self.lock_calls.append(uid)
            self.call_order.append("lock")

        def _release_if_held(self) -> None:
            if self._lock_held and self._lock.locked():
                self._lock_held = False
                self._lock.release()

    repo = _SerialisingRepo(user_id=user_id, current=initial)
    uc = RecalibrateGoals(
        profile_reader=_FakeProfileReader(_BIO),
        tracking_reader=_FakeTrackingReader(),
        goals_repo=repo,
        bus=_NoopBus(),
    )

    async def _invoke():
        try:
            return await uc(user_id=user_id)
        finally:
            # Mirror pg_advisory_xact_lock semantics: lock is released on
            # transaction commit/rollback regardless of branch taken inside
            # the use case. Without this, an early-skip branch
            # (delta_below_threshold, cooldown, ...) would never release
            # the asyncio.Lock and the second gather() leg would hang.
            repo._release_if_held()

    # 5-second deadlock guard: if the try/finally regresses, fail fast
    # instead of letting CI sit forever.
    results = await asyncio.wait_for(
        asyncio.gather(_invoke(), _invoke()),
        timeout=5.0,
    )

    assert all(isinstance(r, RecalibrationResult | RecalibrationSkipped) for r in results)
    assert repo.current is not None

    # Exactly one winner: at most one INSERT lands. The other call either
    # cooldown-skips on the pre-flight read (when ordering puts the second
    # call after the first's commit, days_since=0 < 14d) or hits the
    # IntegrityError downgrade and skips. Either way: ONE insert, never zero.
    inserts = [op for op in repo.call_order if op == "insert"]
    assert len(inserts) == 1, (
        f"expected exactly one INSERT (one winner), got {len(inserts)}: "
        f"call_order={repo.call_order}"
    )

    # Exactly one of the two calls succeeded with RecalibrationResult; the
    # other is RecalibrationSkipped (cooldown OR concurrent_recalibration).
    successes = [r for r in results if isinstance(r, RecalibrationResult)]
    skips = [r for r in results if isinstance(r, RecalibrationSkipped)]
    assert (
        len(successes) == 1 and len(skips) == 1
    ), f"expected one winner + one skipper, got {results}"
    assert skips[0].reason in {"cooldown", "concurrent_recalibration"}

    # At least one advisory-lock acquisition: the winner. The loser may have
    # been short-circuited by the pre-flight cooldown check (an intentional
    # optimisation to avoid lock contention on guaranteed-skip recalibrations).
    assert 1 <= len(repo.lock_calls) <= 2
