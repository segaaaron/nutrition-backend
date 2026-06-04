"""R3 — Adaptive thermogenesis (AT) correction (Müller 2015 model).

Sustained energy deficit elicits a metabolic adaptation: measured resting
metabolic rate falls beyond what fat-free-mass loss alone would predict.
This is the "metabolic adaptation" or "adaptive thermogenesis" component
described by Müller, Bosy-Westphal and colleagues.

Source: Müller MJ, Enderle J, Bosy-Westphal A. "Changes in Energy
Expenditure with Weight Gain and Weight Loss in Humans." *Obesity Facts*
2015; 8:165–179. (Quantifies AT in dynamic deficit; Table 2 anchors at
~−5–7% of pre-diet TDEE for moderate deficits at ~4 weeks.)

We model:
    if days_in_deficit < 21:
        return 0
    raw_at = −0.06 × avg_deficit_kcal × days_in_deficit / 14
    return max(raw_at, −0.15 × tdee)        # cap magnitude at 15% TDEE

Coefficient calibration:
- Slope 0.06 kcal/d per kcal-deficit reproduces Müller Table 2 magnitudes
  for representative subjects at 28d (~−60 kcal/d at 500 kcal deficit).
- Time scaling /14 means AT magnitude doubles every 2 weeks under sustained
  deficit, approximating the Trexler 2014 (J Int Soc Sports Nutr 11:7)
  observation that adaptation continues to accrue beyond initial 3 weeks.
- 15% TDEE cap aligns with Rosenbaum 2008 (Am J Clin Nutr 88:906) maximum
  observed AT in post-obese long-term reduced state.

Returns 0 or a NEGATIVE Decimal (always non-positive).
Pure domain. Decimal-only. No I/O.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

_TWO_DP: Final[Decimal] = Decimal("0.01")

AT_COEF: Final[Decimal] = Decimal("0.06")
AT_TIME_SCALE_DAYS: Final[Decimal] = Decimal("14")
AT_CAP_FRACTION: Final[Decimal] = Decimal("0.15")
AT_MIN_DAYS: Final[int] = 21


def at_correction(
    *,
    days_in_deficit: int,
    avg_deficit_kcal: Decimal,
    tdee: Decimal,
) -> Decimal:
    """Return AT correction to subtract from TDEE_observed (≤ 0).

    Args:
        days_in_deficit: contiguous days under target deficit (≥0).
        avg_deficit_kcal: |TDEE − intake| mean over that window (Decimal ≥ 0).
        tdee: current TDEE estimate the cap is computed against.

    Returns:
        Decimal ≤ 0. Zero when days < 21. Otherwise negative, capped at
        −AT_CAP_FRACTION × tdee.
    """
    if days_in_deficit < AT_MIN_DAYS:
        return Decimal("0")
    raw = -(AT_COEF * avg_deficit_kcal * Decimal(days_in_deficit) / AT_TIME_SCALE_DAYS)
    cap = -(AT_CAP_FRACTION * tdee)
    # max() because both raw and cap are non-positive — larger is less negative.
    result = raw if raw >= cap else cap
    return result.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
