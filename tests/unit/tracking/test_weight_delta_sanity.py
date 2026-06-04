"""ADR-0026 L1 — stricter weight-delta sanity inside `LogWeight`.

Beyond the physiological floor in `tracking.domain.anomaly` (10kg/day),
the use case now enforces a per-day cap of `max(2.0kg, 5% bodyweight)`
to defeat fake weight-loss farming for leaderboard XP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.errors import BusinessRuleViolation
from app.tracking.application.use_cases import LogWeight

pytestmark = pytest.mark.anyio


@dataclass
class _StubBus:
    published: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.published = []

    async def publish(self, evt):  # noqa: ANN001
        self.published.append(evt)


class _StubRepo:
    def __init__(self, last_time: datetime | None, last_weight: Decimal | None) -> None:
        self._last = (last_time, last_weight) if last_time else None
        self.appended: list = []

    async def latest(self, user_id):  # noqa: ANN001, ARG002
        return self._last

    async def append(self, log) -> None:  # noqa: ANN001
        self.appended.append(log)


async def test_delta_within_sanity_accepted():
    uid = uuid4()
    repo = _StubRepo(
        last_time=datetime.now(UTC) - timedelta(days=1),
        last_weight=Decimal("70.0"),
    )
    bus = _StubBus()
    await LogWeight(repo=repo, bus=bus)(user_id=uid, weight_kg=Decimal("71.0"))
    assert len(repo.appended) == 1
    assert len(bus.published) == 1


async def test_delta_exceeds_2kg_floor_rejected_for_low_weight():
    # 35kg user, +2.5kg/day → cap = max(2.0, 0.05*37.5=1.875) = 2.0
    # 2.5 > 2.0 → reject.
    uid = uuid4()
    repo = _StubRepo(
        last_time=datetime.now(UTC) - timedelta(days=1),
        last_weight=Decimal("35.0"),
    )
    bus = _StubBus()
    with pytest.raises(BusinessRuleViolation) as exc_info:
        await LogWeight(repo=repo, bus=bus)(
            user_id=uid, weight_kg=Decimal("37.5")
        )
    assert exc_info.value.detail == "weight_delta_unrealistic"
    assert repo.appended == []


async def test_delta_exceeds_5pct_rejected_for_heavy_weight():
    # 100kg user, +6kg/day → 6 > max(2.0, 0.05*106=5.3) → reject
    uid = uuid4()
    repo = _StubRepo(
        last_time=datetime.now(UTC) - timedelta(days=1),
        last_weight=Decimal("100.0"),
    )
    bus = _StubBus()
    with pytest.raises(BusinessRuleViolation):
        await LogWeight(repo=repo, bus=bus)(
            user_id=uid, weight_kg=Decimal("106.0")
        )


async def test_no_prior_weight_skips_delta_check():
    uid = uuid4()
    repo = _StubRepo(last_time=None, last_weight=None)
    bus = _StubBus()
    await LogWeight(repo=repo, bus=bus)(user_id=uid, weight_kg=Decimal("90.0"))
    assert len(repo.appended) == 1


async def test_delta_spread_over_multiple_days_accepted():
    # 5kg drop over 10 days = 0.5kg/day → ≤ 2.0 cap → accepted
    uid = uuid4()
    repo = _StubRepo(
        last_time=datetime.now(UTC) - timedelta(days=10),
        last_weight=Decimal("80.0"),
    )
    bus = _StubBus()
    await LogWeight(repo=repo, bus=bus)(user_id=uid, weight_kg=Decimal("75.0"))
    assert len(repo.appended) == 1
