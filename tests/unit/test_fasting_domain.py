"""Sprint 7.B — fasting domain invariants."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.tracking.domain.fasting import FastingMethod, FastingSession


def test_target_seconds_matches_hours():
    assert FastingMethod.SIXTEEN.target_seconds == 16 * 3600
    assert FastingMethod.EIGHTEEN.target_seconds == 18 * 3600
    assert FastingMethod.TWENTY.target_seconds == 20 * 3600


def test_start_initialises_open_session():
    fs = FastingSession.start(
        id_=uuid4(),
        user_id=uuid4(),
        method=FastingMethod.SIXTEEN,
    )
    assert fs.end_ts is None
    assert fs.duration_s is None
    assert fs.achieved is False
    assert fs.target_s == 16 * 3600
    assert fs.method_h == 16


def test_stop_marks_achieved_when_duration_meets_target():
    fs = FastingSession.start(
        id_=uuid4(),
        user_id=uuid4(),
        method=FastingMethod.SIXTEEN,
    )
    # Simulate that we started 17h ago.
    fs.start_ts = fs.start_ts - timedelta(hours=17)
    fs.stop()
    assert fs.end_ts is not None
    assert fs.duration_s is not None
    assert fs.duration_s >= 16 * 3600
    assert fs.achieved is True


def test_stop_marks_not_achieved_when_too_short():
    fs = FastingSession.start(
        id_=uuid4(),
        user_id=uuid4(),
        method=FastingMethod.EIGHTEEN,
    )
    fs.start_ts = fs.start_ts - timedelta(hours=10)
    fs.stop()
    assert fs.duration_s is not None
    assert fs.duration_s < 18 * 3600
    assert fs.achieved is False


def test_double_stop_raises():
    fs = FastingSession.start(
        id_=uuid4(),
        user_id=uuid4(),
        method=FastingMethod.SIXTEEN,
    )
    fs.stop()
    with pytest.raises(ValueError):
        fs.stop()


def test_log_window_achieved_derived_from_duration():
    """achieved is computed from duration_s >= target_s, including boundary."""
    fs = FastingSession.start(id_=uuid4(), user_id=uuid4(), method=FastingMethod.SIXTEEN)
    # Exactly at boundary → achieved.
    fs.start_ts = fs.start_ts - timedelta(seconds=16 * 3600)
    fs.stop()
    assert fs.duration_s is not None
    assert fs.duration_s >= 16 * 3600
    assert fs.achieved is True

    # One second short → not achieved.
    fs2 = FastingSession.start(id_=uuid4(), user_id=uuid4(), method=FastingMethod.SIXTEEN)
    fs2.start_ts = fs2.start_ts - timedelta(seconds=16 * 3600 - 1)
    fs2.stop()
    assert fs2.achieved is False


def test_streak_does_not_count_broken_fasts():
    """A session stopped before reaching its target has achieved=False.
    streak_days SQL filters achieved=true, so broken fasts are excluded."""
    fs = FastingSession.start(id_=uuid4(), user_id=uuid4(), method=FastingMethod.SIXTEEN)
    # Stop after only 8h — half the target.
    fs.start_ts = fs.start_ts - timedelta(hours=8)
    fs.stop()
    assert fs.achieved is False, "broken fast must not be marked achieved"
    # Sanity: an achieved fast has achieved=True.
    fs2 = FastingSession.start(id_=uuid4(), user_id=uuid4(), method=FastingMethod.SIXTEEN)
    fs2.start_ts = fs2.start_ts - timedelta(hours=17)
    fs2.stop()
    assert fs2.achieved is True


def test_start_fasting_14h_valid():
    """FastingMethod.FOURTEEN is a valid protocol (target = 14 * 3600 s)."""
    fs = FastingSession.start(
        id_=uuid4(),
        user_id=uuid4(),
        method=FastingMethod.FOURTEEN,
    )
    assert fs.target_s == 14 * 3600
    assert fs.method_h == 14
    assert fs.end_ts is None
    assert fs.achieved is False
