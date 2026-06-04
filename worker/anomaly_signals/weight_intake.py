"""Signal: Pearson correlation between daily weight delta and intake delta.

Physiology requires *positive* correlation across multi-day windows: a
caloric surplus produces weight gain, a deficit produces loss. A
*negative* correlation across 7+ days is statistically incompatible with
the first law of thermodynamics applied to a closed-mass human and is a
strong signal of fabricated logs (e.g. reporting low kcal on days the
scale ticks up).

Score::

    score = 100 - (correlation + 1) * 50

So correlation +1.0 → 0, 0.0 → 50, -1.0 → 100.

Returns ``None`` when (a) fewer than 3 paired (kcal_day, weight_day)
observations exist, or (b) either series has zero variance (correlation
undefined).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker.anomaly_signals import SignalResult

_SQL_DAILY_KCAL = text(
    """
    SELECT date AS d, COALESCE(SUM(kcal), 0)::numeric AS kcal_day
      FROM food_logs
     WHERE user_id = :uid
       AND date >= (current_date - (:days || ' days')::interval)::date
     GROUP BY date
     ORDER BY date
    """
)

_SQL_DAILY_WEIGHT = text(
    """
    SELECT (time AT TIME ZONE 'UTC')::date AS d,
           AVG(weight_kg)::numeric        AS wkg
      FROM weight_logs
     WHERE user_id = :uid
       AND time >= now() - (:days || ' days')::interval
     GROUP BY d
     ORDER BY d
    """
)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    if dx2 == 0.0 or dy2 == 0.0:
        return None
    return float(num / ((dx2**0.5) * (dy2**0.5)))


def _correlation_to_score(corr: float) -> float:
    # Clamp correlation defensively in case of float drift.
    c = max(-1.0, min(1.0, corr))
    return 100.0 - (c + 1.0) * 50.0


async def compute(
    session: AsyncSession, user_id: UUID, window_days: int
) -> SignalResult:
    kcal_rows = (
        await session.execute(
            _SQL_DAILY_KCAL, {"uid": str(user_id), "days": window_days}
        )
    ).all()
    weight_rows = (
        await session.execute(
            _SQL_DAILY_WEIGHT, {"uid": str(user_id), "days": window_days}
        )
    ).all()
    if len(kcal_rows) < 2 or len(weight_rows) < 2:
        return None

    kcal_by_day: dict[object, float] = {
        r[0]: float(Decimal(r[1])) for r in kcal_rows
    }
    weight_by_day: dict[object, float] = {
        r[0]: float(Decimal(r[1])) for r in weight_rows
    }

    # Compute day-over-day deltas keyed by date.
    def deltas(series: dict[object, float]) -> list[tuple[object, float]]:
        keys = sorted(series.keys())  # type: ignore[type-var]
        out: list[tuple[object, float]] = []
        for i in range(1, len(keys)):
            out.append((keys[i], series[keys[i]] - series[keys[i - 1]]))
        return out

    kcal_deltas = dict(deltas(kcal_by_day))
    weight_deltas = dict(deltas(weight_by_day))
    common = sorted(set(kcal_deltas.keys()) & set(weight_deltas.keys()))  # type: ignore[type-var]
    if len(common) < 3:
        return None

    xs = [kcal_deltas[d] for d in common]
    ys = [weight_deltas[d] for d in common]
    corr = _pearson(xs, ys)
    if corr is None:
        return None
    return _correlation_to_score(corr)
