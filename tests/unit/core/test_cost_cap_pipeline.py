"""Unit — cost_cap.pre_check batches Redis GETs into ONE pipeline RTT.

Previously: 3 sequential awaits (kill_switch GET + user GET + org GET).
Now: a single `pipeline().execute()` call.

These tests verify:
  * pipe.execute() is awaited exactly once
  * the pipeline receives the expected GETs (kill_switch + user + org)
  * functional behaviour is preserved (kill switch, user cap, org cap, warning)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core import cost_cap
from app.core.errors import CostCapExceeded


def _mk_redis(pipeline_results: list[Any]) -> MagicMock:
    """Build a mock Redis whose pipeline().execute() yields given results."""
    pipe = MagicMock()
    pipe.get = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=pipeline_results)
    r = MagicMock()
    r.pipeline = MagicMock(return_value=pipe)
    return r


@pytest.mark.asyncio
async def test_pre_check_single_rtt_with_user() -> None:
    r = _mk_redis([None, b"0.05", b"1.00"])  # kill, user, org
    with patch.object(cost_cap, "get_redis", return_value=r):
        decision = await cost_cap.pre_check(user_id=uuid4(), estimate_usd=0.01)
    pipe = r.pipeline.return_value
    pipe.execute.assert_awaited_once()
    # 3 GETs queued: kill switch + user + org
    assert pipe.get.call_count == 3
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_pre_check_single_rtt_anonymous() -> None:
    r = _mk_redis([None, b"2.00"])  # kill, org
    with patch.object(cost_cap, "get_redis", return_value=r):
        decision = await cost_cap.pre_check(user_id=None, estimate_usd=0.01)
    pipe = r.pipeline.return_value
    pipe.execute.assert_awaited_once()
    assert pipe.get.call_count == 2  # no user GET
    assert decision.allowed is True
    assert decision.spent_usd == 0.0


@pytest.mark.asyncio
async def test_pre_check_kill_switch_raises() -> None:
    r = _mk_redis(["1", b"0", b"0"])
    with patch.object(cost_cap, "get_redis", return_value=r):
        with pytest.raises(CostCapExceeded):
            await cost_cap.pre_check(user_id=uuid4(), estimate_usd=0.01)


@pytest.mark.asyncio
async def test_pre_check_user_cap_breach_raises() -> None:
    # 100 USD already spent vs ~1.50 cap -> breach
    r = _mk_redis([None, b"100.0", b"0.0"])
    with patch.object(cost_cap, "get_redis", return_value=r):
        with pytest.raises(CostCapExceeded):
            await cost_cap.pre_check(user_id=uuid4(), estimate_usd=0.01)


@pytest.mark.asyncio
async def test_pre_check_org_cap_breach_raises() -> None:
    # huge org spend vs 500 default cap
    r = _mk_redis([None, b"0.0", b"9999.0"])
    with patch.object(cost_cap, "get_redis", return_value=r):
        with pytest.raises(CostCapExceeded):
            await cost_cap.pre_check(user_id=uuid4(), estimate_usd=0.01)


@pytest.mark.asyncio
async def test_pre_check_warning_threshold() -> None:
    # 80% of 1.50 = 1.20 → spent 1.25 + estimate 0.01 → warn
    r = _mk_redis([None, b"1.25", b"0.0"])
    with patch.object(cost_cap, "get_redis", return_value=r):
        decision = await cost_cap.pre_check(user_id=uuid4(), estimate_usd=0.01)
    assert decision.allowed is True
    assert decision.warning is True
