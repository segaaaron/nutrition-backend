"""Plan state machine — every disallowed edge raises IllegalTransition."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.errors import IllegalTransition
from app.plan.domain.entities import Plan
from app.plan.domain.state_machine import advance


def _plan(status: str = "active", current_day: int = 1, total_days: int = 7) -> Plan:
    return Plan(
        id=uuid4(), user_id=uuid4(), type="week",
        total_days=total_days, current_day=current_day, status=status,  # type: ignore[arg-type]
        goal=None, meals_per_day=3, preferences=[], kcal_target=2000,
        version=0, created_at=datetime.now(timezone.utc),
    )


def test_active_cancel_transitions_to_cancelled() -> None:
    p = _plan()
    assert advance(p, "CANCEL").status == "cancelled"


def test_active_regenerate_bumps_version() -> None:
    p = _plan()
    assert advance(p, "REGENERATE").version == 1


def test_day_complete_advances_current_day() -> None:
    p = _plan(current_day=1, total_days=7)
    out = advance(p, "DAY_COMPLETE")
    assert out.current_day == 2
    assert out.status == "active"


def test_day_complete_on_last_day_marks_completed() -> None:
    p = _plan(current_day=7, total_days=7)
    out = advance(p, "DAY_COMPLETE")
    assert out.status == "completed"


def test_completed_terminal_raises_on_any_event() -> None:
    p = _plan(status="completed")
    for evt in ("MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"):
        with pytest.raises(IllegalTransition):
            advance(p, evt)  # type: ignore[arg-type]


def test_cancelled_terminal_raises_on_any_event() -> None:
    p = _plan(status="cancelled")
    for evt in ("MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"):
        with pytest.raises(IllegalTransition):
            advance(p, evt)  # type: ignore[arg-type]
