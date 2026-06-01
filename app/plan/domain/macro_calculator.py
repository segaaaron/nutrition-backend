"""H1.1-H1.3 macro math. Pure domain. Decimal-only. No I/O. No framework."""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from app.shared.domain.macro_tolerance import MACRO_TOLERANCE

Sex = Literal["male", "female"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]

_TOL: Final[Decimal] = Decimal(str(MACRO_TOLERANCE))
_ZERO: Final[Decimal] = Decimal("0")
_ONE_G: Final[Decimal] = Decimal("1")
_TWO_DP: Final[Decimal] = Decimal("0.01")

MACRO_INVARIANT_FRACTIONS: Final[dict[str, Decimal]] = {
    "protein_min": Decimal("0.10"),
    "protein_max": Decimal("0.40"),
    "carbs_min": Decimal("0.30"),
    "carbs_max": Decimal("0.65"),
    "fat_min": Decimal("0.20"),
    "fat_max": Decimal("0.40"),
}


class MacroError(Exception):
    """Base macro error."""


class MacroBackAdjustFailed(MacroError):
    """Back-adjust loop did not converge within max_iter."""


class MacroOutOfRange(MacroError):
    """Macro value outside invariant range."""


def derive_kcal_from_macros(
    protein_g: Decimal, carbs_g: Decimal, fat_g: Decimal
) -> Decimal:
    """Atwater: 4P + 4C + 9F kcal."""
    kcal = protein_g * Decimal("4") + carbs_g * Decimal("4") + fat_g * Decimal("9")
    return kcal.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


def compute_carbs_from_kcal_target(
    kcal: Decimal, protein_g: Decimal, fat_g: Decimal
) -> Decimal:
    """Solve C from kcal=4P+4C+9F. Floor at 0. Round to 1g."""
    remaining = kcal - protein_g * Decimal("4") - fat_g * Decimal("9")
    carbs = remaining / Decimal("4")
    if carbs < _ZERO:
        carbs = _ZERO
    return carbs.quantize(_ONE_G, rounding=ROUND_HALF_EVEN)


def back_adjust_macros(
    target_kcal: Decimal,
    protein_g: Decimal,
    fat_g: Decimal,
    *,
    max_iter: int = 5,
    tolerance: Decimal | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """H1.1 back-adjust carbs ±1g until |derived-target|/target <= tolerance."""
    tol = tolerance if tolerance is not None else _TOL
    carbs = compute_carbs_from_kcal_target(target_kcal, protein_g, fat_g)
    for _ in range(max_iter + 1):
        derived = derive_kcal_from_macros(protein_g, carbs, fat_g)
        rel = abs(derived - target_kcal) / target_kcal
        if rel <= tol:
            return (protein_g, carbs, fat_g)
        if derived < target_kcal:
            carbs = carbs + _ONE_G
        else:
            if carbs <= _ZERO:
                break
            carbs = carbs - _ONE_G
    raise MacroBackAdjustFailed(
        f"could_not_converge: target={target_kcal} last_derived={derived} max_iter={max_iter}"
    )


def lbm_kg(
    weight_kg: Decimal,
    sex: Sex,
    bodyfat_pct: Decimal | None = None,
) -> Decimal:
    """H1.2 LBM. From bodyfat if given, else sex-fallback."""
    if bodyfat_pct is not None:
        lbm = weight_kg * (Decimal("1") - bodyfat_pct / Decimal("100"))
    else:
        factor = Decimal("0.82") if sex == "male" else Decimal("0.75")
        lbm = weight_kg * factor
    return lbm.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


def protein_target_g(
    *,
    weight_kg: Decimal,
    sex: Sex,
    goal: Goal,
    bodyfat_pct: Decimal | None = None,
) -> Decimal:
    """H1.2 protein anchored to LBM. Clamp 0.6-2.5 g/kg total weight."""
    k_by_goal: dict[str, Decimal] = {
        "weight_loss": Decimal("1.8"),
        "maintain": Decimal("1.6"),
        "muscle_gain": Decimal("2.0"),
        "weight_gain": Decimal("1.8"),
        "health": Decimal("1.4"),
    }
    k = k_by_goal[goal]
    lbm = lbm_kg(weight_kg, sex, bodyfat_pct)
    p = k * lbm
    floor = Decimal("0.6") * weight_kg
    ceil = Decimal("2.5") * weight_kg
    if p < floor:
        p = floor
    if p > ceil:
        p = ceil
    return p.quantize(_ONE_G, rounding=ROUND_HALF_EVEN)


def fat_target_g(
    *,
    weight_kg: Decimal,
    kcal: Decimal,
    goal: Goal,
) -> Decimal:
    """H1.3 fat = max(0.6 g/kg floor, goal_pct * kcal / 9)."""
    fat_pct_by_goal: dict[str, Decimal] = {
        "weight_loss": Decimal("0.25"),
        "maintain": Decimal("0.28"),
        "muscle_gain": Decimal("0.25"),
        "weight_gain": Decimal("0.28"),
        "health": Decimal("0.30"),
    }
    fat_pct = fat_pct_by_goal[goal]
    floor = Decimal("0.6") * weight_kg
    from_kcal = (kcal * fat_pct) / Decimal("9")
    f = floor if floor > from_kcal else from_kcal
    return f.quantize(_ONE_G, rounding=ROUND_HALF_EVEN)
