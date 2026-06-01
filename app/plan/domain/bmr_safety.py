"""H1.4 BMR selection + TDEE + goal + safety floor. Pure domain. Decimal-only."""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

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
        super().__init__(
            f"kcal_target_below_bmr_safety_floor: target={target} < floor={floor}"
        )
        self.target = target
        self.floor = floor


def mifflin_st_jeor(
    *,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
    sex: Sex,
) -> Decimal:
    """BMR = 10W + 6.25H - 5A + (5 male / -161 female). kcal int."""
    base = (
        Decimal("10") * weight_kg
        + Decimal("6.25") * height_cm
        - Decimal("5") * Decimal(age)
    )
    offset = Decimal("5") if sex == "male" else Decimal("-161")
    return (base + offset).quantize(_INT, rounding=ROUND_HALF_EVEN)


def cunningham(*, lbm_kg: Decimal) -> Decimal:
    """BMR = 500 + 22 * LBM. Athletes with known LBM."""
    return (Decimal("500") + Decimal("22") * lbm_kg).quantize(
        _INT, rounding=ROUND_HALF_EVEN
    )


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
    """TDEE = BMR * activity multiplier."""
    mult: dict[str, Decimal] = {
        "sedentary": Decimal("1.2"),
        "lightly_active": Decimal("1.375"),
        "moderately_active": Decimal("1.55"),
        "very_active": Decimal("1.725"),
        "extra_active": Decimal("1.9"),
    }
    return (bmr * mult[activity_level]).quantize(_INT, rounding=ROUND_HALF_EVEN)


def apply_goal_to_tdee(*, tdee_val: Decimal, goal: Goal) -> Decimal:
    """Goal kcal: weight_loss min(500, 25% tdee) deficit; muscle/weight gain surplus."""
    if goal == "weight_loss":
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
    """H1.4 raise if kcal_target < BMR * 0.9. Else passthrough."""
    floor = bmr * Decimal("0.9")
    if kcal_target < floor:
        raise KcalTargetBelowSafetyFloor(target=kcal_target, floor=floor)
    return kcal_target


_LACTATION_KCAL_SURPLUS = Decimal("500")


def apply_lactation_adjustment(
    *, kcal_target: Decimal, conditions: frozenset[str]
) -> Decimal:
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
