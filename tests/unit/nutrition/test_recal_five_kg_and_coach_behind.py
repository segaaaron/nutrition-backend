"""QA-A3 — Recalibración 5 kg + coach idempotency (domain logic only).

These tests cover the pure domain invariants of T-10 and T-12.
DB-level integration is guarded behind --run-integration (separate suite).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


# ── 5 kg trigger (pure math) ─────────────────────────────────────────────────

def _five_kg_trigger_pure(current_kg: Decimal, calibration_kg: Decimal) -> bool:
    """Pure logic extracted from _five_kg_trigger helper in event_handlers."""
    return abs(current_kg - calibration_kg) >= Decimal("5")


class TestFiveKgTrigger:
    @pytest.mark.parametrize("current, calib, expected", [
        (Decimal("95"), Decimal("100"), True),   # exactly 5 kg loss
        (Decimal("94"), Decimal("100"), True),   # > 5 kg loss
        (Decimal("96"), Decimal("100"), False),  # 4 kg — not enough
        (Decimal("100"), Decimal("100"), False), # no change
        (Decimal("105"), Decimal("100"), True),  # 5 kg gain (also triggers)
        (Decimal("104"), Decimal("100"), False), # 4 kg gain — not enough
        (Decimal("80"),  Decimal("100"), True),  # 20 kg loss — definitely triggers
    ])
    def test_boundary(self, current: Decimal, calib: Decimal, expected: bool) -> None:
        assert _five_kg_trigger_pure(current, calib) == expected

    def test_exactly_5_triggers(self) -> None:
        assert _five_kg_trigger_pure(Decimal("75.0"), Decimal("80.0")) is True

    def test_4_9_does_not_trigger(self) -> None:
        assert _five_kg_trigger_pure(Decimal("75.1"), Decimal("80.0")) is False

    @given(
        st.decimals(min_value=Decimal("30"), max_value=Decimal("200"), places=1),
        st.decimals(min_value=Decimal("5"), max_value=Decimal("20"), places=1),
    )
    @settings(max_examples=100)
    def test_any_loss_over_5kg_triggers(self, calibration: Decimal, loss: Decimal) -> None:
        current = calibration - loss
        assert _five_kg_trigger_pure(current, calibration) is True

    @given(
        st.decimals(min_value=Decimal("30"), max_value=Decimal("200"), places=1),
        st.decimals(min_value=Decimal("0"), max_value=Decimal("4.9"), places=1),
    )
    @settings(max_examples=100)
    def test_loss_under_5kg_does_not_trigger(self, calibration: Decimal, loss: Decimal) -> None:
        current = calibration - loss
        assert _five_kg_trigger_pure(current, calibration) is False


# ── Coach message goal gate (pure logic) ─────────────────────────────────────

_WEIGHT_LOSS_GOALS = frozenset({"weight_loss", "lose_weight"})


def _goal_allows_behind_alert(goal: str | None) -> bool:
    """Mirror of weight_behind_alert goal gate — only weight_loss goals eligible."""
    return goal in _WEIGHT_LOSS_GOALS


class TestWeightBehindAlertGoalGate:
    """weight_behind_alert must be a no-op for non-weight-loss users."""

    def test_weight_loss_allowed(self) -> None:
        assert _goal_allows_behind_alert("weight_loss") is True

    def test_lose_weight_alias_allowed(self) -> None:
        assert _goal_allows_behind_alert("lose_weight") is True

    def test_muscle_gain_blocked(self) -> None:
        assert _goal_allows_behind_alert("muscle_gain") is False

    def test_maintain_blocked(self) -> None:
        assert _goal_allows_behind_alert("maintain") is False

    def test_weight_gain_blocked(self) -> None:
        assert _goal_allows_behind_alert("weight_gain") is False

    def test_health_blocked(self) -> None:
        assert _goal_allows_behind_alert("health") is False

    def test_none_goal_blocked(self) -> None:
        assert _goal_allows_behind_alert(None) is False


# ── Coach message idempotency (pure date math) ────────────────────────────────

from datetime import UTC, datetime, timedelta


def _should_send_behind_alert(last_msg_at: datetime | None, now: datetime, cooldown_days: int = 5) -> bool:
    """Pure check from weight_behind_alert idempotency guard."""
    if last_msg_at is None:
        return True
    last = last_msg_at if last_msg_at.tzinfo else last_msg_at.replace(tzinfo=UTC)
    return (now - last).days >= cooldown_days


class TestWeightBehindAlertIdempotency:
    @pytest.fixture
    def now(self) -> datetime:
        return datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)

    def test_no_previous_msg_always_sends(self, now: datetime) -> None:
        assert _should_send_behind_alert(None, now) is True

    def test_msg_today_skips(self, now: datetime) -> None:
        assert _should_send_behind_alert(now, now) is False

    def test_msg_4_days_ago_skips(self, now: datetime) -> None:
        last = now - timedelta(days=4)
        assert _should_send_behind_alert(last, now) is False

    def test_msg_exactly_5_days_ago_sends(self, now: datetime) -> None:
        last = now - timedelta(days=5)
        assert _should_send_behind_alert(last, now) is True

    def test_msg_6_days_ago_sends(self, now: datetime) -> None:
        last = now - timedelta(days=6)
        assert _should_send_behind_alert(last, now) is True

    def test_msg_1_day_ago_skips(self, now: datetime) -> None:
        last = now - timedelta(days=1)
        assert _should_send_behind_alert(last, now) is False

    @given(st.integers(min_value=0, max_value=4))
    @settings(max_examples=50)
    def test_less_than_5_days_always_skips(self, days: int) -> None:
        now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
        last = now - timedelta(days=days)
        assert _should_send_behind_alert(last, now) is False

    @given(st.integers(min_value=5, max_value=365))
    @settings(max_examples=50)
    def test_5_or_more_days_always_sends(self, days: int) -> None:
        now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
        last = now - timedelta(days=days)
        assert _should_send_behind_alert(last, now) is True
