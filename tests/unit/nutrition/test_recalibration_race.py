"""Sprint 3 D5 — Recalibration race-condition lock-ordering check (unit).

Only the deterministic sequence assertion lives here: the use case must
acquire its per-user advisory lock BEFORE the write (``expire_current_and_insert``)
and BEFORE the post-lock ``get_current`` re-read used to decide the
INSERT. No concurrency, no IntegrityError simulation — those require
real Postgres + pg_advisory_xact_lock and live under
``tests/integration/nutrition/test_recalibration_race.py`` behind
``@pytest.mark.integration``.

Why not "lock before ANY read"? The use case intentionally performs a
*pre-flight* ``get_current`` to short-circuit the 14d cooldown skip
without taking the advisory lock — taking the lock for a guaranteed
skip only adds contention (and historically deadlocked the integration
suite). The contract this test pins is therefore:

    * lock acquisition occurs.
    * The lock occurs BEFORE the write call.
    * The lock occurs BEFORE the *post-lock* re-read of ``get_current``
      (the read whose result actually feeds the recalibration math).

Keeping this as a unit test means it runs on every push (cheap, ms, no
Docker) and guards against an easy regression: moving the lock
acquisition below the write — or removing it — would silently
reintroduce the read-then-write race that pg_advisory_xact_lock
exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import EventBus
from app.nutrition.application.use_cases import RecalibrateGoals
from app.nutrition.domain.state_machine import NutritionalGoals


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_goals(user_id: UUID, valid_from: datetime | None = None) -> NutritionalGoals:
    return NutritionalGoals.new(
        user_id=user_id,
        kcal_min=2400,
        kcal_max=2600,
        protein_g=140,
        carbs_g=300,
        fat_g=80,
        water_ml=2500,
        bmr=1800,
        tdee=2500,
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
        self.weights = [(i, 80.0 - i * 0.05) for i in range(14)]
        self.kcal_in = [2500] * 14

    async def weight_series_14d(self, u: UUID) -> list[tuple[int, float]]:
        return self.weights

    async def kcal_in_14d(self, u: UUID) -> list[int]:
        return self.kcal_in


@dataclass
class _FakeGoalsRepo:
    user_id: UUID
    current: NutritionalGoals | None
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
        self.current = new_goals
        return new_goals


class _NoopBus(EventBus):
    async def publish(self, *_a, **_kw):  # type: ignore[override]
        return None


@pytest.mark.asyncio
async def test_advisory_lock_acquired_before_post_lock_read_and_write():
    """Order matters: lock must precede the post-lock re-read and the write.

    The use case does ONE pre-flight ``get_current`` for the cooldown
    short-circuit (no lock needed for a guaranteed skip), then takes
    the advisory lock, then RE-reads ``get_current`` and may write.
    This test pins that the lock sits strictly between the pre-flight
    read and any subsequent repo interaction.
    """
    user_id = uuid4()
    repo = _FakeGoalsRepo(user_id=user_id, current=_make_goals(user_id))

    uc = RecalibrateGoals(
        profile_reader=_FakeProfileReader(
            {
                "weight_kg": Decimal("80"),
                "height_cm": Decimal("180"),
                "age": 30,
                "sex": "male",
                "goal": "maintain",
                "activity_level": "moderately_active",
            }
        ),
        tracking_reader=_FakeTrackingReader(),
        goals_repo=repo,
        bus=_NoopBus(),
    )
    await uc(user_id=user_id)

    assert repo.lock_calls == [user_id], "advisory lock must be acquired exactly once"
    assert "lock" in repo.call_order

    lock_idx = repo.call_order.index("lock")
    get_current_indices = [i for i, op in enumerate(repo.call_order) if op == "get_current"]
    assert get_current_indices, "use case must read goals at least once"

    # Pre-flight read (cooldown short-circuit) is BEFORE the lock.
    assert get_current_indices[0] < lock_idx, (
        "pre-flight get_current must run before lock acquisition "
        "(cooldown short-circuit avoids unnecessary advisory-lock contention)"
    )
    # Every other repo interaction (post-lock re-read, insert) is AFTER the lock.
    post_lock_ops = repo.call_order[lock_idx + 1 :]
    assert all(op != "lock" for op in post_lock_ops), "lock taken at most once"
    # If there is a post-lock get_current, it must trail the lock.
    if len(get_current_indices) > 1:
        assert get_current_indices[1] > lock_idx
    # Any write must trail the lock.
    if "insert" in repo.call_order:
        assert repo.call_order.index("insert") > lock_idx
