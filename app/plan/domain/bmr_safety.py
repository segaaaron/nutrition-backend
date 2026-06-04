"""H1.4 BMR selection + TDEE + goal + safety floor. Pure domain. Decimal-only."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from app.nutrition.domain.mifflin_st_jeor import mifflin_st_jeor
from app.plan.domain.macro_calculator import lbm_kg as _lbm_kg

Sex = Literal["male", "female"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
ActivityLevel = Literal[
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]
BmrMethod = Literal["mifflin", "cunningham"]

_INT: Final[Decimal] = Decimal("1")


class KcalTargetBelowSafetyFloor(Exception):
    """H1.4 kcal_target violated BMR * 0.9 floor."""

    def __init__(self, target: Decimal, floor: Decimal) -> None:
        super().__init__(f"kcal_target_below_bmr_safety_floor: target={target} < floor={floor}")
        self.target = target
        self.floor = floor


def cunningham(*, lbm_kg: Decimal) -> Decimal:
    """BMR = 500 + 22 * LBM. Athletes with known LBM.

    Source: Cunningham JJ. A reanalysis of the factors influencing basal
    metabolic rate in normal adults. Am J Clin Nutr 1980;33(11):2372-2374.
    Preferred over Mifflin in lean/athletic populations where total body
    weight overestimates metabolically active mass.
    """
    return (Decimal("500") + Decimal("22") * lbm_kg).quantize(_INT, rounding=ROUND_HALF_EVEN)


def select_bmr(
    *,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
    sex: Sex,
    bodyfat_pct: Decimal | None = None,
    athletic: bool = False,
) -> tuple[Decimal, BmrMethod]:
    """Cunningham if athletic+bodyfat known; else Mifflin."""
    if athletic and bodyfat_pct is not None:
        lbm = _lbm_kg(weight_kg, sex, bodyfat_pct)
        return (cunningham(lbm_kg=lbm), "cunningham")
    return (
        mifflin_st_jeor(weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex),
        "mifflin",
    )


def tdee(*, bmr: Decimal, activity_level: ActivityLevel) -> Decimal:
    """TDEE = BMR * activity multiplier.

    Source: Harris-Benedict activity factors as standardized by the
    Mayo Clinic / ADA practice. Discrete ladder per FAO/WHO/UNU 2001
    "Human Energy Requirements" PAL classes.
    """
    mult: dict[str, Decimal] = {
        # PAL 1.40-1.69 — sedentary lifestyle (FAO/WHO/UNU 2001).
        "sedentary": Decimal("1.2"),
        # PAL 1.55-1.69 — active or moderately active lifestyle, low end.
        "lightly_active": Decimal("1.375"),
        # PAL 1.70-1.99 — vigorous lifestyle.
        "moderately_active": Decimal("1.55"),
        "very_active": Decimal("1.725"),
        # PAL ≥2.00 — vigorous occupational + training load (rare).
        "extra_active": Decimal("1.9"),
    }
    return (bmr * mult[activity_level]).quantize(_INT, rounding=ROUND_HALF_EVEN)


def apply_goal_to_tdee(*, tdee_val: Decimal, goal: Goal) -> Decimal:
    """Goal kcal: weight_loss min(500, 25% tdee) deficit; muscle/weight gain surplus.

    Sources:
    - 500 kcal/day deficit ≈ 0.45 kg/week loss (Wishnofsky 1958 conversion,
      JAMA 168:445) — capped at 25% TDEE to avoid metabolic adaptation.
    - 250 kcal/day muscle-gain surplus: Slater & Phillips 2011 (J Sports Sci
      29 Suppl 1:S67) optimal range to support lean accretion without
      excess fat gain.
    - 300 kcal/day weight-gain surplus for underweight repletion.
    """
    if goal == "weight_loss":
        # 500 kcal/day cap or 25% TDEE, whichever smaller. Source: Hall 2011
        # (Lancet 378:826) — quasi-linear early phase before adaptive
        # thermogenesis blunts response.
        deficit = Decimal("500")
        pct = tdee_val * Decimal("0.25")
        cut = deficit if deficit < pct else pct
        out = tdee_val - cut
    elif goal == "muscle_gain":
        out = tdee_val + Decimal("250")
    elif goal == "weight_gain":
        out = tdee_val + Decimal("300")
    else:
        out = tdee_val
    return out.quantize(_INT, rounding=ROUND_HALF_EVEN)


def enforce_bmr_safety_floor(*, kcal_target: Decimal, bmr: Decimal) -> Decimal:
    """H1.4 raise if kcal_target < BMR * 0.9. Else passthrough.

    Source: AND/ACSM/Dietitians of Canada Joint Position 2016 (Med Sci
    Sports Exerc 48:543) — sustained intake below BMR risks RED-S and
    metabolic adaptation. 0.9 factor adds a 10% guardrail margin.
    """
    floor = bmr * Decimal("0.9")
    if kcal_target < floor:
        raise KcalTargetBelowSafetyFloor(target=kcal_target, floor=floor)
    return kcal_target


_LACTATION_KCAL_SURPLUS = Decimal("500")


def apply_lactation_adjustment(*, kcal_target: Decimal, conditions: frozenset[str]) -> Decimal:
    """Add lactation energy surplus to kcal target when applicable.

    Per IOM DRI for breastfeeding women, energy needs rise ~+500 kcal/day
    during exclusive lactation (months 0-6). Caller is responsible for
    deciding whether the user is in active lactation; this function only
    applies the surplus when `"lactation" in conditions`.

    Returns input unchanged otherwise.
    """
    if "lactation" in conditions:
        return kcal_target + _LACTATION_KCAL_SURPLUS
    return kcal_target


# Pregnancy energy surplus per trimester (IOM DRI 2002):
# T1: no increase needed; T2: +340 kcal/day; T3: +452 kcal/day.
_PREGNANCY_KCAL_SURPLUS_BY_TRIMESTER: dict[str, Decimal] = {
    "first": Decimal("0"),
    "second": Decimal("340"),
    "third": Decimal("452"),
}


def apply_trimester_adjustment(
    *, kcal_target: Decimal, trimester: Literal["first", "second", "third"] | None
) -> Decimal:
    """Add pregnancy energy surplus by trimester (IOM DRI 2002).

    No-op if `trimester is None`. Caller passes `None` for non-pregnant
    users.
    """
    if trimester is None:
        return kcal_target
    surplus = _PREGNANCY_KCAL_SURPLUS_BY_TRIMESTER[trimester]
    return kcal_target + surplus
