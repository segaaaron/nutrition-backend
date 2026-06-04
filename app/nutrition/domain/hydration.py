"""Water target.

Heuristic — 35 ml/kg bodyweight + 350 ml per activity factor step above
sedentary. Clamped to [1500, 5000] ml.

Sources:
- 35 ml/kg/day: EFSA 2010 Scientific Opinion on Dietary Reference Values
  for Water (EFSA J 8(3):1459) — population AI ~2.0 L women / 2.5 L men
  approximates 30-40 ml/kg.
- +350 ml per PAL step: ACSM Position Stand 2007 (Med Sci Sports Exerc
  39:377) — fluid replacement during exercise scales with sweat rate.
- [1500, 5000] ml clamp: hyponatremia risk above 5 L (Hew-Butler 2015,
  Clin J Sport Med 25:303); 1.5 L is the practical minimum AI floor.

R8 — condition-aware fluid restriction (defense in depth):
- CKD: KDOQI 2020 Nutrition Practice Guideline for Nutrition in CKD
  (Am J Kidney Dis 76(3)S1) — fluid intake individualised but commonly
  restricted to ≤1500 ml/day in CKD-4/5 or fluid-overloaded states.
- CHF: AHA/ACC/HFSA 2022 Guideline for the Management of Heart Failure
  (Circulation 145:e895) — fluid restriction ≤1500-2000 ml/day in moderate
  to severe HF; we apply the more conservative 1500 ml cap.

NOVA scope: nutrition planning only. Cap is a SAFETY GUARD, not a medical
prescription. Users should follow their physician's individual fluid
allowance — the cap exists to prevent the algorithm from recommending a
volume that contradicts standard guideline ceilings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

# Threshold-based PAL → bonus mL mapping. Bisect-style: pick the *highest*
# threshold ≤ activity_factor. Decimal-keyed to avoid float-equality lookups
# on arbitrary Decimal inputs (e.g. ActivityFactor("1.55") vs 1.55 float ≠
# 1.5500000000000003 hash mismatch). Ordered ascending; linear scan is
# constant-time for n=5.
#
# Step deltas mirror the original {1.20→0, 1.375→1, 1.55→2, 1.725→3, 1.90→4}
# table multiplied by 350 mL per ACSM 2007 fluid-replacement scaling.
_FACTOR_THRESHOLDS: Final[tuple[tuple[Decimal, int], ...]] = (
    (Decimal("1.200"), 0),
    (Decimal("1.375"), 350),
    (Decimal("1.550"), 700),
    (Decimal("1.725"), 1050),
    (Decimal("1.900"), 1400),
)

CKD_FLUID_CAP_ML: Final[int] = 1500
CHF_FLUID_CAP_ML: Final[int] = 1500


def _activity_bonus_ml(activity_factor: Decimal) -> int:
    """Return the bonus mL for the highest threshold ≤ activity_factor.

    Below the sedentary floor (1.20) we still return 0 — physiologically, fluid
    needs scale up with PAL, never down. Above the top threshold (1.90) we
    saturate at the maximum bonus.
    """
    bonus = 0
    for threshold, b in _FACTOR_THRESHOLDS:
        if activity_factor >= threshold:
            bonus = b
        else:
            break
    return bonus


def compute_water_ml(
    *,
    weight_kg: Decimal | float,
    activity_factor: Decimal | float,
    conditions: frozenset[str] | set[str] | None = None,
) -> int:
    w = float(weight_kg)
    af = activity_factor if isinstance(activity_factor, Decimal) else Decimal(str(activity_factor))
    base = int(round(35 * w))
    bonus = _activity_bonus_ml(af)
    target = max(1500, min(5000, base + bonus))

    # R8 — defense-in-depth fluid restriction caps.
    if conditions:
        if "ckd" in conditions:
            target = min(target, CKD_FLUID_CAP_ML)
        if "chf" in conditions:
            target = min(target, CHF_FLUID_CAP_ML)
    return target
