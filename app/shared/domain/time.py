"""Time utilities — UTC-only, DST-safe day indexing.

Why this module exists
----------------------
`RecalibrationInput.weights` is typed as `list[tuple[int, float]]` where
`int` is a *day index*. Historically the contract was implicit and callers
sometimes used `local_date.toordinal()` or `(now - start).days` against
naive datetimes. Both flavours break across DST transitions and across
clients in different timezones:

  * `toordinal()` on a localised civil date jumps by 0 or 2 on the DST
    Sunday in some regions because the civil date itself shifts.
  * `(now - start).days` on naive datetimes silently mixes wall clock and
    UTC, producing off-by-one slope artefacts that propagate into the OLS
    fit and ultimately into TDEE recalibration.

Contract
--------
Every `day_index` supplied to the recalibration pipeline MUST be computed
via `utc_day_index(dt)`. It is defined as the integer number of UTC days
between `dt.astimezone(UTC).date()` and `UTC_EPOCH_DATE`. Inputs MUST be
timezone-aware (CLAUDE.md non-negotiable principle #3); naive inputs raise
`ValueError` rather than silently degrading.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Final

UTC_EPOCH_DATE: Final[date] = date(1970, 1, 1)


def utc_today() -> date:
    """Current UTC civil date — server-timezone-independent "today".

    `date.today()` uses the host's local timezone: a server in UTC-5
    rolls the date 5 hours later than the rest of the system (Redis
    markers, `now()` SQL defaults, event timestamps), which made streak
    and daily-goal boundaries drift depending on where the container
    ran. Always use this instead of `date.today()` in app code.
    """
    return datetime.now(UTC).date()


def utc_day_index(dt: datetime) -> int:
    """Return integer day count from `UTC_EPOCH_DATE` to UTC date of `dt`.

    Requires `dt.tzinfo is not None` — naive datetimes raise `ValueError`.
    Two `datetime` values that refer to the same UTC instant always map to
    the same index, regardless of their original `tzinfo`. DST transitions
    in any local zone never shift the result by more than one day, and the
    boundary itself is the UTC midnight boundary (not the local one).
    """
    if dt.tzinfo is None:
        raise ValueError(
            "utc_day_index requires a timezone-aware datetime; "
            "got naive — see CLAUDE.md non-negotiable principle #3."
        )
    utc_date = dt.astimezone(UTC).date()
    return (utc_date - UTC_EPOCH_DATE).days
