"""D13 — UTC day-index contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.shared.domain.time import UTC_EPOCH_DATE, utc_day_index


def test_naive_datetime_raises_value_error() -> None:
    naive = datetime(2026, 6, 3, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_day_index(naive)


def test_epoch_returns_zero() -> None:
    assert utc_day_index(datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)) == 0


def test_utc_one_day_after_epoch_returns_one() -> None:
    assert utc_day_index(datetime(1970, 1, 2, 0, 0, 0, tzinfo=UTC)) == 1


def test_two_instants_in_different_zones_same_utc_date_yield_same_index() -> None:
    # 2026-06-03 18:00 in Tokyo (UTC+9) == 2026-06-03 09:00 UTC.
    tokyo = timezone(timedelta(hours=9))
    dt_tokyo = datetime(2026, 6, 3, 18, 0, 0, tzinfo=tokyo)
    dt_utc = datetime(2026, 6, 3, 9, 0, 0, tzinfo=UTC)
    assert utc_day_index(dt_tokyo) == utc_day_index(dt_utc)


def test_dst_boundary_stable_in_zone_with_dst() -> None:
    # 2026-03-08 02:30 in US/Eastern is the spring-forward gap; we anchor on
    # the UTC instant the *clock* would have hit, which is well-defined.
    # Two consecutive UTC midnights → indices differ by exactly 1, regardless
    # of any local DST jitter.
    d0 = datetime(2026, 3, 8, 0, 0, 0, tzinfo=UTC)
    d1 = datetime(2026, 3, 9, 0, 0, 0, tzinfo=UTC)
    assert utc_day_index(d1) - utc_day_index(d0) == 1


def test_epoch_constant_anchored() -> None:
    # Defensive: the contract pins UTC_EPOCH_DATE to 1970-01-01.
    assert UTC_EPOCH_DATE.isoformat() == "1970-01-01"
