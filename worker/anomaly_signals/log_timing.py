"""Signal: Shannon entropy of log inter-arrival gaps.

Low entropy across hour-of-day buckets is a bot-like signature (logs
clustered into the same handful of slots). The score is the *inverse* of
the normalised entropy: a perfectly uniform distribution maps to ``0``
(benign) and a single-bucket distribution maps to ``100`` (suspicious).

Formula
-------
Let ``H`` be the Shannon entropy of the hour-of-day histogram (base-2,
bits) over all food_logs + weight_logs in the past ``window_days``. The
upper bound is ``H_max = log2(window_days * 24)`` (one observation per
hour over the full window). We score::

    score = 100 - (H / H_max) * 100

Returns ``None`` when fewer than two observations exist (entropy is
undefined / pathologically low and would emit a false positive).
"""

from __future__ import annotations

import math
from collections import Counter
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker.anomaly_signals import SignalResult

_SQL = text(
    """
    SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC')::int AS hour
      FROM food_logs
     WHERE user_id = :uid
       AND created_at >= now() - (:days || ' days')::interval
    UNION ALL
    SELECT EXTRACT(HOUR FROM time AT TIME ZONE 'UTC')::int AS hour
      FROM weight_logs
     WHERE user_id = :uid
       AND time >= now() - (:days || ' days')::interval
    """
)


async def compute(
    session: AsyncSession, user_id: UUID, window_days: int
) -> SignalResult:
    rows = (
        await session.execute(_SQL, {"uid": str(user_id), "days": window_days})
    ).all()
    hours = [int(r[0]) for r in rows]
    if len(hours) < 2:
        return None
    return _entropy_score(hours, window_days)


def _entropy_score(hours: list[int], window_days: int) -> float:
    """Pure function — exposed for unit/property testing."""
    n = len(hours)
    if n < 2:
        # Pathological — caller should treat as None; defensive default benign.
        return 0.0
    counts = Counter(hours)
    entropy = 0.0
    for c in counts.values():
        p = c / n
        entropy -= p * math.log2(p)
    h_max = math.log2(max(2, window_days * 24))
    normalised = entropy / h_max
    score = 100.0 - normalised * 100.0
    return max(0.0, min(100.0, score))
