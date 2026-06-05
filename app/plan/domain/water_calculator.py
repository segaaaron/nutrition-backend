"""NOVA hybrid hydration target calculator — deterministic, decimal-precise.

Formula (in Decimal throughout — no floats):

    base       = weight_kg * 35
    kcal_boost = max(0, (kcal_daily - 2000) * 0.5)
    total      = base + kcal_boost

Modifiers (applied in deterministic order):
    +500  if activity == "moderately_active"
    +1000 if activity == "very_active"
    +500  if region == "latam" AND month in {10, 11, 12, 1, 2, 3}  (hot season)
    +250  if goal == "weight_loss"
    +500  if goal == "muscle_gain"
    +300  if pregnant
    +700  if lactating

Safety caps (EFSA/IOM bounds — hyponatremia + hypovolemia guards):
    total = clamp(total, 1500, 4000)

Medical override (ALWAYS wins, applied last):
    if "ckd" in conditions OR "heart_failure" in conditions:
        total = min(total, 1500)

Numerical contract:
    * All intermediate math uses ``decimal.Decimal``.
    * Final ``total_ml`` materialises as ``int`` via ``ROUND_HALF_EVEN``
      banker's rounding to avoid float drift and even-odd bias.
    * Deterministic: identical inputs ⇒ identical output, forever.

Sources:
    * EFSA 2010 — Scientific Opinion on Dietary Reference Values for Water
      (EFSA J 8(3):1459) ≈ 35 ml/kg/day baseline.
    * IOM 2005 — Dietary Reference Intakes for Water (≈3.7 L men, 2.7 L women).
    * ACSM 2007 Position Stand — fluid replacement scales with activity.
    * Hew-Butler 2015 (Clin J Sport Med 25:303) — hyponatremia risk > 4-5 L.
    * KDOQI 2020 (Am J Kidney Dis 76(3) S1) — CKD-4/5 fluid restriction ≤ 1.5 L.
    * AHA/ACC/HFSA 2022 (Circulation 145:e895) — HF fluid restriction ≤ 1.5-2 L.

NOVA scope: nutrition planning only. The medical override is a SAFETY
GUARD, not a clinical prescription — physician-individualised allowances
take precedence in clinical settings.

Example:
    >>> from decimal import Decimal
    >>> t = calculate_water_target(
    ...     weight_kg=Decimal("70"),
    ...     kcal_daily=2200,
    ...     activity="moderately_active",
    ...     region="latam",
    ...     month=12,
    ...     goal="weight_loss",
    ...     conditions=frozenset(),
    ... )
    >>> t.total_ml  # 70*35=2450, +100 kcal_boost, +500 mod_active, +500 latam_hot, +250 wl
    3800
    >>> t.n_glasses
    16
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

# ---------------------------------------------------------------------------
# Constants (all Decimal — never float).
# ---------------------------------------------------------------------------

_ML_PER_KG: Final[Decimal] = Decimal(35)
_KCAL_BOOST_BASELINE: Final[Decimal] = Decimal(2000)
_KCAL_BOOST_FACTOR: Final[Decimal] = Decimal("0.5")

_ACTIVITY_MODIFIERS: Final[dict[str, Decimal]] = {
    "moderately_active": Decimal(500),
    "very_active": Decimal(1000),
}

_GOAL_MODIFIERS: Final[dict[str, Decimal]] = {
    "weight_loss": Decimal(250),
    "muscle_gain": Decimal(500),
}

_PREGNANT_BONUS: Final[Decimal] = Decimal(300)
_LACTATING_BONUS: Final[Decimal] = Decimal(700)

_LATAM_HOT_BONUS: Final[Decimal] = Decimal(500)
_LATAM_HOT_MONTHS: Final[frozenset[int]] = frozenset({10, 11, 12, 1, 2, 3})

SAFETY_MIN_ML: Final[Decimal] = Decimal(1500)
SAFETY_MAX_ML: Final[Decimal] = Decimal(4000)

MEDICAL_OVERRIDE_CAP_ML: Final[Decimal] = Decimal(1500)
MEDICAL_OVERRIDE_CONDITIONS: Final[frozenset[str]] = frozenset({"ckd", "heart_failure"})

DEFAULT_GLASS_ML: Final[int] = 250


# ---------------------------------------------------------------------------
# Output dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WaterTarget:
    """Result of :func:`calculate_water_target`.

    Attributes:
        total_ml: Final daily water target in millilitres (int, post-cap).
        glass_ml: Size of one glass (default 250 ml).
        n_glasses: Number of glasses to hit the target (ceil division).
        capped_by_medical: True iff CKD/HF override clamped the target.
        capped_by_safety: True iff hit hard floor (1500) or ceiling (4000)
            BEFORE the medical override was considered. Medical clamp does
            not flip this flag (a CKD user already capped to 1500 by the
            medical rule is reported via ``capped_by_medical`` only).
    """

    total_ml: int
    glass_ml: int
    n_glasses: int
    capped_by_medical: bool
    capped_by_safety: bool


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def calculate_water_target(
    *,
    weight_kg: Decimal,
    kcal_daily: int,
    activity: str,
    region: str,
    month: int,
    goal: str,
    conditions: frozenset[str],
    pregnant: bool = False,
    lactating: bool = False,
    glass_ml: int = DEFAULT_GLASS_ML,
) -> WaterTarget:
    """Compute the daily water target per the NOVA hybrid algorithm.

    Args:
        weight_kg: Body weight in kg (Decimal, strictly > 0).
        kcal_daily: Daily kcal target (int, strictly > 0).
        activity: One of ``sedentary | lightly_active | moderately_active |
            very_active | extra_active`` (unknown values contribute 0).
        region: Region code, e.g. ``latam``, ``eu``, ``us``. Only ``latam``
            currently has a climate modifier.
        month: Month of year, 1-12.
        goal: Nutritional goal, e.g. ``weight_loss``, ``muscle_gain``,
            ``maintain``, ``health``, ``weight_gain`` (unknown values
            contribute 0).
        conditions: Frozen set of medical condition codes (lowercase).
            Presence of ``ckd`` or ``heart_failure`` triggers the
            ≤ 1500 ml medical override.
        pregnant: True iff the user is pregnant (any trimester).
        lactating: True iff the user is currently lactating.
        glass_ml: Glass size in ml (default 250). Must be > 0.

    Returns:
        :class:`WaterTarget` with the final ``total_ml`` (post-cap) and
        derived glass count.

    Raises:
        ValueError: If any numeric input is non-positive or month is out
            of range.
    """
    # ---- Validate inputs ----------------------------------------------
    if not isinstance(weight_kg, Decimal):  # pragma: no cover — defensive
        raise TypeError("weight_kg must be Decimal (no float in nutrition math)")
    if weight_kg <= 0:
        raise ValueError(f"weight_kg must be > 0, got {weight_kg}")
    if kcal_daily <= 0:
        raise ValueError(f"kcal_daily must be > 0, got {kcal_daily}")
    if not (1 <= month <= 12):
        raise ValueError(f"month must be in 1..12, got {month}")
    if glass_ml <= 0:
        raise ValueError(f"glass_ml must be > 0, got {glass_ml}")

    # ---- Base + kcal boost --------------------------------------------
    base = weight_kg * _ML_PER_KG
    kcal_excess = Decimal(kcal_daily) - _KCAL_BOOST_BASELINE
    kcal_boost = max(Decimal(0), kcal_excess * _KCAL_BOOST_FACTOR)
    total = base + kcal_boost

    # ---- Deterministic modifier order ---------------------------------
    # 1) activity
    total += _ACTIVITY_MODIFIERS.get(activity, Decimal(0))
    # 2) climate (LatAm hot season Oct-Mar — summer in southern hemisphere
    #    + peak heat in equatorial / tropical northern LatAm)
    if region == "latam" and month in _LATAM_HOT_MONTHS:
        total += _LATAM_HOT_BONUS
    # 3) goal
    total += _GOAL_MODIFIERS.get(goal, Decimal(0))
    # 4) pregnancy
    if pregnant:
        total += _PREGNANT_BONUS
    # 5) lactation
    if lactating:
        total += _LACTATING_BONUS

    # ---- Safety caps (pre-medical) ------------------------------------
    pre_clamp = total
    if total < SAFETY_MIN_ML:
        total = SAFETY_MIN_ML
    elif total > SAFETY_MAX_ML:
        total = SAFETY_MAX_ML
    capped_by_safety = total != pre_clamp

    # ---- Medical override (ALWAYS last, ALWAYS wins) ------------------
    capped_by_medical = False
    if conditions & MEDICAL_OVERRIDE_CONDITIONS:
        total = min(total, MEDICAL_OVERRIDE_CAP_ML)
        capped_by_medical = True

    # ---- Materialise to int (banker's rounding) -----------------------
    total_int = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))

    # ---- Glass count (ceil) -------------------------------------------
    # Integer ceil division — exact, no float.
    n_glasses = -(-total_int // glass_ml)

    return WaterTarget(
        total_ml=total_int,
        glass_ml=glass_ml,
        n_glasses=n_glasses,
        capped_by_medical=capped_by_medical,
        capped_by_safety=capped_by_safety,
    )
