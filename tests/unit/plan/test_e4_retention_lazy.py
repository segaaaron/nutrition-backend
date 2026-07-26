"""E4 — unit tests for _compute_retention_context (H3/H4/H5 lazy fields).

Uses a stub AsyncSession + injectable _today parameter (no date.today() patching).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from app.plan.presentation.schemas import RetentionNudge, TodaySummary, WeekRecap


# ---------------------------------------------------------------------------
# Stub session helpers
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value

    def mappings(self) -> "_MappingsResult":
        return _MappingsResult(self._value)


class _MappingsResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _StubSession:
    """Returns values keyed by SQL fragment (case-insensitive substring match)."""

    def __init__(self, rows: dict[str, Any]) -> None:
        self._rows = {k.lower(): v for k, v in rows.items()}

    async def execute(self, stmt: Any, params: Any) -> _ScalarResult:
        sql = str(stmt).strip().lower()
        for pattern, value in self._rows.items():
            if pattern in sql:
                return _ScalarResult(value)
        return _ScalarResult(None)


class _KcalSession:
    """Special stub that returns a mapping row for the kcal query."""

    def __init__(self, kcal_row: dict | None, scalar_rows: dict[str, Any]) -> None:
        self._kcal = kcal_row
        self._scalars = {k.lower(): v for k, v in scalar_rows.items()}

    async def execute(self, stmt: Any, params: Any) -> Any:
        sql = str(stmt).strip().lower()
        if "kcal_min" in sql:
            return _KcalResult(self._kcal)
        for pattern, value in self._scalars.items():
            if pattern in sql:
                return _ScalarResult(value)
        return _ScalarResult(None)


class _KcalResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar(self) -> None:
        return None

    def mappings(self) -> "_KcalMappings":
        return _KcalMappings(self._row)


class _KcalMappings:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _call(session: Any, today: date) -> dict:
    from app.plan.presentation.router import _compute_retention_context

    return await _compute_retention_context(session, uuid4(), _today=today)


# ---------------------------------------------------------------------------
# H3 — retention_nudge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h3_streak_at_risk_days_since_1() -> None:
    today = date(2026, 7, 14)
    last_log = date(2026, 7, 13)  # 1 day ago
    session = _StubSession(
        {
            "max(date) from food_logs": last_log,
            "value from streaks": 5,
            "created_at::date from users": date(2026, 7, 7),
            "count(distinct date) from food_logs": 4,
        }
    )
    result = await _call(session, today)
    nudge = result.get("retention_nudge")
    assert isinstance(nudge, RetentionNudge)
    assert nudge.type == "streak_at_risk"
    assert nudge.streak_days == 5
    assert nudge.days_away is None
    assert "5" in nudge.message_es


@pytest.mark.asyncio
async def test_h3_streak_at_risk_days_since_2() -> None:
    today = date(2026, 7, 14)
    last_log = date(2026, 7, 12)  # 2 days ago
    session = _StubSession(
        {
            "max(date) from food_logs": last_log,
            "value from streaks": 3,
            "created_at::date from users": date(2026, 7, 1),
            "count(distinct date) from food_logs": 2,
        }
    )
    result = await _call(session, today)
    nudge = result.get("retention_nudge")
    assert isinstance(nudge, RetentionNudge)
    assert nudge.type == "streak_at_risk"


@pytest.mark.asyncio
async def test_h3_comeback_days_since_4() -> None:
    today = date(2026, 7, 14)
    last_log = date(2026, 7, 10)  # 4 days ago
    session = _StubSession(
        {
            "max(date) from food_logs": last_log,
            "value from streaks": 0,
            "created_at::date from users": date(2026, 7, 1),
            "count(distinct date) from food_logs": 1,
        }
    )
    result = await _call(session, today)
    nudge = result.get("retention_nudge")
    assert isinstance(nudge, RetentionNudge)
    assert nudge.type == "comeback"
    assert nudge.days_away == 4


@pytest.mark.asyncio
async def test_h3_no_nudge_when_logged_today() -> None:
    today = date(2026, 7, 14)
    session = _StubSession(
        {
            "max(date) from food_logs": today,
            "value from streaks": 3,
            "created_at::date from users": date(2026, 7, 11),  # 3 days ago
            "count(distinct date) from food_logs": 3,
        }
    )
    result = await _call(session, today)
    assert "retention_nudge" not in result


@pytest.mark.asyncio
async def test_h3_week1_strong_day_8_streak_6() -> None:
    today = date(2026, 7, 14)
    session = _StubSession(
        {
            "max(date) from food_logs": today,  # days_since = 0
            "value from streaks": 6,
            "created_at::date from users": date(2026, 7, 6),  # days_active = 8
            "count(distinct date) from food_logs": 5,
        }
    )
    result = await _call(session, today)
    nudge = result.get("retention_nudge")
    # days_active=8 (7≤8≤9), streak=6 (≥5) → week1_strong
    assert isinstance(nudge, RetentionNudge)
    assert nudge.type == "week1_strong"


@pytest.mark.asyncio
async def test_h3_no_week1_strong_streak_too_low() -> None:
    today = date(2026, 7, 14)
    session = _StubSession(
        {
            "max(date) from food_logs": today,
            "value from streaks": 2,  # < 5, no week1_strong
            "created_at::date from users": date(2026, 7, 6),  # days_active=8
            "count(distinct date) from food_logs": 2,
        }
    )
    result = await _call(session, today)
    assert "retention_nudge" not in result


# ---------------------------------------------------------------------------
# H4 — week_recap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h4_present_on_sunday() -> None:
    sunday = date(2026, 7, 19)  # isoweekday=7
    assert sunday.isoweekday() == 7
    session = _StubSession(
        {
            "max(date) from food_logs": sunday,
            "value from streaks": 7,
            "created_at::date from users": date(2026, 6, 29),
            "count(distinct date) from food_logs": 5,
        }
    )
    result = await _call(session, sunday)
    recap = result.get("week_recap")
    assert isinstance(recap, WeekRecap)
    assert recap.days_logged == 5
    assert recap.days_total == 7


@pytest.mark.asyncio
async def test_h4_present_on_day_7_multiple() -> None:
    monday = date(2026, 7, 14)  # not Sunday
    assert monday.isoweekday() != 7
    session = _StubSession(
        {
            "max(date) from food_logs": monday,
            "value from streaks": 7,
            "created_at::date from users": date(2026, 7, 7),  # days_active = 7 (multiple)
            "count(distinct date) from food_logs": 7,
        }
    )
    result = await _call(session, monday)
    recap = result.get("week_recap")
    assert isinstance(recap, WeekRecap)
    assert recap.days_logged == 7
    assert "perfecta" in recap.message_es.lower() or "perfect" in recap.message_en.lower()


@pytest.mark.asyncio
async def test_h4_absent_on_non_sunday_non_multiple() -> None:
    wednesday = date(2026, 7, 15)  # isoweekday=3, days_active=4 (not multiple of 7)
    assert wednesday.isoweekday() == 3
    session = _StubSession(
        {
            "max(date) from food_logs": wednesday,
            "value from streaks": 3,
            "created_at::date from users": date(2026, 7, 11),  # days_active=4
            "count(distinct date) from food_logs": 3,
        }
    )
    result = await _call(session, wednesday)
    assert "week_recap" not in result


# ---------------------------------------------------------------------------
# H5 — today_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h5_kcal_math() -> None:
    today = date(2026, 7, 14)
    session = _KcalSession(
        kcal_row={"target": 1800, "logged": 900},
        scalar_rows={
            "max(date) from food_logs": None,
            "value from streaks": 0,
            "created_at::date from users": date(2026, 7, 7),
            "count(distinct date) from food_logs": 0,
        },
    )
    result = await _call(session, today)
    summary = result.get("today_summary")
    assert isinstance(summary, TodaySummary)
    assert summary.kcal_logged == 900
    assert summary.kcal_target == 1800
    assert summary.kcal_remaining == 900
    assert summary.pct_complete == 50


@pytest.mark.asyncio
async def test_h5_pct_capped_at_100_remaining_0() -> None:
    today = date(2026, 7, 14)
    session = _KcalSession(
        kcal_row={"target": 1800, "logged": 2200},
        scalar_rows={
            "max(date) from food_logs": None,
            "value from streaks": 0,
            "created_at::date from users": date(2026, 7, 7),
            "count(distinct date) from food_logs": 0,
        },
    )
    result = await _call(session, today)
    summary = result.get("today_summary")
    assert isinstance(summary, TodaySummary)
    assert summary.pct_complete == 100
    assert summary.kcal_remaining == 0


@pytest.mark.asyncio
async def test_h5_absent_when_no_goals() -> None:
    today = date(2026, 7, 14)
    session = _KcalSession(
        kcal_row=None,  # no nutritional goals
        scalar_rows={
            "max(date) from food_logs": None,
            "value from streaks": 0,
            "created_at::date from users": date(2026, 7, 7),
            "count(distinct date) from food_logs": 0,
        },
    )
    result = await _call(session, today)
    assert "today_summary" not in result
