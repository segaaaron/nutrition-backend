"""Unit — C12: LogWater respects optional `at` timestamp."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.tracking.application.use_cases import LogWater


@pytest.fixture()
def _repo():
    repo = MagicMock()
    repo.append = AsyncMock()
    repo.total_today = AsyncMock(return_value=500)
    return repo


@pytest.fixture()
def _bus():
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.mark.asyncio
async def test_log_water_uses_provided_at(_repo, _bus):
    uc = LogWater(repo=_repo, bus=_bus)
    explicit_ts = datetime(2026, 8, 25, 14, 30, 0, tzinfo=UTC)
    await uc(user_id=uuid4(), ml=250, at=explicit_ts)
    call_args = _repo.append.call_args[0][0]
    assert call_args.time == explicit_ts


@pytest.mark.asyncio
async def test_log_water_defaults_to_now_when_at_absent(_repo, _bus):
    before = datetime.now(UTC)
    uc = LogWater(repo=_repo, bus=_bus)
    await uc(user_id=uuid4(), ml=250)
    after = datetime.now(UTC)
    call_args = _repo.append.call_args[0][0]
    assert before <= call_args.time <= after
