"""Signal: claimed kcal vs TDEE baseline.

Computes ``ratio = mean(kcal_per_day) / tdee_baseline``. Values around
1.0 are physiologic; ``ratio > 3.0`` is biochemically implausible (the
human GI tract cannot process > 3x TDEE sustainably) and points at
fabricated logs.

Score::

    score = clip( (ratio - 1.0) / 2.0 * 100, 0, 100 )

So ratio 1.0 → 0, ratio 2.0 → 50, ratio ≥ 3.0 → 100.

Returns ``None`` if (a) no active nutritional_goals row exists for the
user or (b) zero food_logs in window.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker.anomaly_signals import SignalResult

_SQL_TDEE = text(
    """
    SELECT tdee
      FROM nutritional_goals
     WHERE user_id = :uid
       AND (valid_to IS NULL OR valid_to > now())
     ORDER BY valid_from DESC
     LIMIT 1
    """
)

_SQL_KCAL = text(
    """
    SELECT COALESCE(SUM(kcal), 0) AS total_kcal,
           COUNT(DISTINCT date)   AS active_days
      FROM food_logs
     WHERE user_id = :uid
       AND created_at >= now() - (:days || ' days')::interval
    """
)


def _ratio_to_score(ratio: float) -> float:
    score = (ratio - 1.0) / 2.0 * 100.0
    return max(0.0, min(100.0, score))


async def compute(
    session: AsyncSession, user_id: UUID, window_days: int
) -> SignalResult:
    tdee_row = (
        await session.execute(_SQL_TDEE, {"uid": str(user_id)})
    ).first()
    if tdee_row is None or tdee_row[0] is None or int(tdee_row[0]) <= 0:
        return None

    kcal_row = (
        await session.execute(
            _SQL_KCAL, {"uid": str(user_id), "days": window_days}
        )
    ).first()
    if kcal_row is None:
        return None
    total_kcal_raw = kcal_row[0] or 0
    active_days = int(kcal_row[1] or 0)
    if active_days <= 0:
        return None

    # food_logs.kcal is NUMERIC → SQLAlchemy returns Decimal.
    total_kcal = Decimal(total_kcal_raw)
    avg_kcal_per_day = float(total_kcal) / active_days
    tdee = float(tdee_row[0])
    ratio = avg_kcal_per_day / tdee
    return _ratio_to_score(ratio)
