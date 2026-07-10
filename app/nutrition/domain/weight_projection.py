"""Expected weight trajectory from the energy-balance identity (Sprint A2).

Pure domain, Decimal-only. Given a kcal target vs TDEE, project the weekly
weight change the plan is expected to produce, with a confidence band.

  weekly_kg = (kcal_target - tdee) * 7 / KCAL_PER_KG

KCAL_PER_KG = 7700 (Wishnofsky 1958, JAMA 168:445). Modern work (Hall 2008,
Int J Obes 32:573) puts the steady-state cost closer to ~9400 kcal/kg, so the
7700 point estimate tends to OVERstate the magnitude of change. We surface a
±25% confidence band to communicate that honestly rather than a false-precision
single number — transparency is the product's trust lever, not a spurious
decimal.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, NamedTuple

KCAL_PER_KG: Final[Decimal] = Decimal("7700")
_CI_FRACTION: Final[Decimal] = Decimal("0.25")
_2DP: Final[Decimal] = Decimal("0.01")


class WeightProjection(NamedTuple):
    """kg/week the plan is expected to move (negative = loss)."""

    weekly_kg: Decimal
    ci_low_kg: Decimal
    ci_high_kg: Decimal


def expected_weekly_change(*, kcal_target: int, tdee: int) -> WeightProjection:
    """Project weekly weight change (kg) with a ±25% confidence band.

    Positive = gain, negative = loss. A maintenance target (kcal_target == tdee)
    yields 0 with a 0-width band. The band is symmetric around the point
    estimate and reported to 2 decimals.
    """
    weekly = (Decimal(kcal_target) - Decimal(tdee)) * Decimal("7") / KCAL_PER_KG
    margin = abs(weekly) * _CI_FRACTION
    return WeightProjection(
        weekly_kg=_q(weekly),
        ci_low_kg=_q(weekly - margin),
        ci_high_kg=_q(weekly + margin),
    )


def _q(v: Decimal) -> Decimal:
    return v.quantize(_2DP, rounding=ROUND_HALF_EVEN)
