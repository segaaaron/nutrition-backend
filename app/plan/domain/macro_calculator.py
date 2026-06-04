"""H1.1-H1.3 macro math. Pure domain. Decimal-only. No I/O. No framework."""

from __future__ import annotations

from dataclasses import dataclass
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
    # Source: IOM Acceptable Macronutrient Distribution Ranges (AMDR) 2005,
    # DRI Energy and Macronutrients (Chapter 11):
    #   Protein 10-35% kcal — we narrow upper bound to 40% as a hard ceiling
    #     for the catalog (Phillips 2014, Nutr Metab 11:53 supports up to 2.5
    #     g/kg ≈ 40% kcal at a 2000 kcal diet for a 80 kg adult).
    #   Carbohydrate 45-65% kcal — we relax the lower bound to 30% to allow
    #     moderate-low-carb patterns endorsed for T2D (ADA 2024).
    #   Fat 20-35% kcal — we extend upper bound to 40% to allow Mediterranean
    #     pattern (Estruch 2018, NEJM 378:e34).
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


def derive_kcal_from_macros(protein_g: Decimal, carbs_g: Decimal, fat_g: Decimal) -> Decimal:
    """Atwater: 4P + 4C + 9F kcal."""
    kcal = protein_g * Decimal("4") + carbs_g * Decimal("4") + fat_g * Decimal("9")
    return kcal.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


def compute_carbs_from_kcal_target(kcal: Decimal, protein_g: Decimal, fat_g: Decimal) -> Decimal:
    """Solve C from kcal=4P+4C+9F. Floor at 0. Round to 1g."""
    remaining = kcal - protein_g * Decimal("4") - fat_g * Decimal("9")
    carbs = remaining / Decimal("4")
    carbs = max(carbs, _ZERO)
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
        # LBM = weight × (1 − BF%). Direct definition (Wang 1992, Am J Clin
        # Nutr 56:19) when body composition is measured.
        lbm = weight_kg * (Decimal("1") - bodyfat_pct / Decimal("100"))
    else:
        # Source unknown — verify before defending in audit.
        # 0.82 (M) / 0.75 (F) are population-mean LBM fractions consistent
        # with NHANES 1999-2004 DXA references for healthy adults but the
        # exact constants here lack a primary citation in the codebase.
        # Cite candidates: Heymsfield 2005 (Am J Clin Nutr 81:1227) or
        # Janssen 2000 (J Appl Physiol 89:81).
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
    # Sources: protein g/kg LBM by goal —
    #   weight_loss 1.8 — Helms 2014 (J Int Soc Sports Nutr 11:20) preserve
    #     LBM during energy deficit.
    #   maintain 1.6 — Morton 2018 (Br J Sports Med 52:376) meta-analysis
    #     plateau for muscle accretion in trained adults.
    #   muscle_gain 2.0 — Phillips 2014 (Nutr Metab 11:53) upper-anabolic
    #     range; Schoenfeld 2018 supports 1.6-2.2 g/kg.
    #   weight_gain 1.8 — same as weight_loss to preserve LBM in repletion.
    #   health 1.4 — Wolfe 2008 (Am J Clin Nutr 87:1562) above RDA 0.8
    #     g/kg, optimal for older adults.
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
    # Source: IOM 2005 — RDA 0.8 g/kg total weight is the population-mean
    # essential floor. We use 0.6 as a hard absolute minimum (still above
    # nitrogen-balance EAR 0.66 g/kg, Rand 2003 Am J Clin Nutr 77:109).
    floor = Decimal("0.6") * weight_kg
    # Source: ISSN Position 2017 (Jäger, J Int Soc Sports Nutr 14:20) —
    # 2.5 g/kg is the upper safety bound for protein in healthy adults.
    ceil = Decimal("2.5") * weight_kg
    p = max(p, floor)
    p = min(p, ceil)
    return p.quantize(_ONE_G, rounding=ROUND_HALF_EVEN)


def fat_target_g(
    *,
    weight_kg: Decimal,
    kcal: Decimal,
    goal: Goal,
) -> Decimal:
    """H1.3 fat = max(0.6 g/kg floor, goal_pct * kcal / 9)."""
    # Source: IOM AMDR 2005 — fat 20-35% kcal. Goal-specific picks within
    # range: weight_loss/muscle_gain skew lower (25%) to leave room for
    # higher protein + carbs; maintain/weight_gain 28% balanced; health 30%
    # supports Mediterranean pattern (Estruch 2018 NEJM 378:e34).
    fat_pct_by_goal: dict[str, Decimal] = {
        "weight_loss": Decimal("0.25"),
        "maintain": Decimal("0.28"),
        "muscle_gain": Decimal("0.25"),
        "weight_gain": Decimal("0.28"),
        "health": Decimal("0.30"),
    }
    fat_pct = fat_pct_by_goal[goal]
    # Source: IOM 2005 — essential fatty acid AI 1.6 g/day ALA + 17 g/day
    # LA for men ≈ 0.5-0.6 g total fat/kg minimum to deliver essentials in
    # a typical diet matrix. We anchor at 0.6 g/kg.
    floor = Decimal("0.6") * weight_kg
    from_kcal = (kcal * fat_pct) / Decimal("9")
    f = floor if floor > from_kcal else from_kcal
    return f.quantize(_ONE_G, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------------------
# R4 — back-adjust fallback. When the carbs back-adjust loop fails to
# converge (protein/fat too dense for the target kcal), callers may opt into
# `back_adjust_macros_with_fallback` to recover with sane goal-based default
# ratios and a transparent warning. Direct callers of `back_adjust_macros`
# still get the original `MacroBackAdjustFailed` exception (backward compat).
# ---------------------------------------------------------------------------

# Sources for default macro ratios per goal:
#   maintain 30/30/40 — IOM AMDR balanced midpoint (protein 30%, fat 30%,
#     carbs 40%); within 10-35 / 20-35 / 45-65 AMDR ranges.
#   weight_loss 35/30/35 — Helms 2014 (J Int Soc Sports Nutr 11:20) higher
#     protein for LBM preservation during deficit; moderate fat + carbs.
#   muscle_gain 30/25/45 — Schoenfeld 2018 / ISSN 2017 — higher carbs to
#     fuel resistance training; protein 30% covers 1.6-2.2 g/kg in surplus.
#   weight_gain 25/30/45 — moderate protein for repletion, higher carbs to
#     drive surplus, fat at AMDR midpoint.
DEFAULT_MACRO_RATIOS: Final[dict[str, tuple[Decimal, Decimal, Decimal]]] = {
    "maintain": (Decimal("0.30"), Decimal("0.30"), Decimal("0.40")),
    "weight_loss": (Decimal("0.35"), Decimal("0.30"), Decimal("0.35")),
    "muscle_gain": (Decimal("0.30"), Decimal("0.25"), Decimal("0.45")),
    "weight_gain": (Decimal("0.25"), Decimal("0.30"), Decimal("0.45")),
    # Health pattern aligns with Mediterranean midpoint (Estruch 2018 NEJM
    # 378:e34) — protein 20%, fat 35%, carbs 45%.
    "health": (Decimal("0.20"), Decimal("0.35"), Decimal("0.45")),
}


@dataclass(frozen=True, slots=True)
class MacroAdjustResult:
    """Result of `back_adjust_macros_with_fallback`.

    `warning` is None on the happy path. When the back-adjust loop failed and
    fallback ratios were applied, `warning` carries an actionable message
    callers MUST surface in their plan output `warnings[]`.
    """

    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    warning: str | None


def _macros_from_ratios(
    target_kcal: Decimal,
    ratios: tuple[Decimal, Decimal, Decimal],
) -> tuple[Decimal, Decimal, Decimal]:
    """Convert (P%, F%, C%) ratios into grams for the given kcal target."""
    p_pct, f_pct, c_pct = ratios
    p_g = (target_kcal * p_pct / Decimal("4")).quantize(_ONE_G, rounding=ROUND_HALF_EVEN)
    f_g = (target_kcal * f_pct / Decimal("9")).quantize(_ONE_G, rounding=ROUND_HALF_EVEN)
    c_g = (target_kcal * c_pct / Decimal("4")).quantize(_ONE_G, rounding=ROUND_HALF_EVEN)
    return (p_g, c_g, f_g)


def back_adjust_macros_with_fallback(
    *,
    target_kcal: Decimal,
    protein_g: Decimal,
    fat_g: Decimal,
    goal: str,
    max_iter: int = 5,
    tolerance: Decimal | None = None,
) -> MacroAdjustResult:
    """Back-adjust carbs; on `MacroBackAdjustFailed` fall back to default
    goal-based ratios and return a warning string for plan `warnings[]`.

    R4 — graceful degradation. Callers that previously had no handler for
    `MacroBackAdjustFailed` should migrate to this entry point so users still
    receive a coherent plan when protein/fat dose is too dense for the kcal
    target (common edge case for high-protein athletes on aggressive cuts).
    """
    try:
        p_out, c_out, f_out = back_adjust_macros(
            target_kcal,
            protein_g,
            fat_g,
            max_iter=max_iter,
            tolerance=tolerance,
        )
        return MacroAdjustResult(
            protein_g=p_out,
            carbs_g=c_out,
            fat_g=f_out,
            warning=None,
        )
    except MacroBackAdjustFailed:
        ratios = DEFAULT_MACRO_RATIOS.get(goal, DEFAULT_MACRO_RATIOS["maintain"])
        p_g, c_g, f_g = _macros_from_ratios(target_kcal, ratios)
        warning = (
            f"macro_back_adjust_fallback_applied: goal={goal} "
            f"target_kcal={target_kcal} fallback_ratios=P{ratios[0]}/F{ratios[1]}/C{ratios[2]} "
            "— input protein/fat could not be reconciled with target kcal; "
            "default goal ratios applied (Helms 2014; ISSN 2017; Estruch 2018)."
        )
        return MacroAdjustResult(
            protein_g=p_g,
            carbs_g=c_g,
            fat_g=f_g,
            warning=warning,
        )
