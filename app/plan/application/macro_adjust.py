"""Plan-application macro adjust scaffolding (Sprint 3 D2).

`back_adjust_macros` raises `MacroBackAdjustFailed` when the input
protein/fat dose cannot be reconciled with the target kcal (high-protein
athletes on aggressive cuts, kcal floor at 800 with 2.2 g/kg protein on a
70 kg male, etc.). There is currently no application-layer caller of
`back_adjust_macros` directly, but plan-generation is WIP and any future
caller MUST default to the fallback path so users still receive a coherent
plan and a transparent warning instead of a 500.

Use `safe_back_adjust(...)` from plan-gen instead of calling
`back_adjust_macros` directly. The helper:

  * delegates to `back_adjust_macros_with_fallback`,
  * collects the optional warning into the supplied `warnings` list,
  * returns the macro triple ready for downstream consumers.

This module is intentionally tiny — it exists to be the obvious wiring
point so the next plan-gen edit defaults to the safe pattern.
"""

from __future__ import annotations

from decimal import Decimal

from app.plan.domain.macro_calculator import (
    MacroAdjustResult,
    back_adjust_macros_with_fallback,
)


def safe_back_adjust(
    *,
    target_kcal: Decimal,
    protein_g: Decimal,
    fat_g: Decimal,
    goal: str,
    warnings: list[str],
    max_iter: int = 5,
    tolerance: Decimal | None = None,
) -> MacroAdjustResult:
    """Back-adjust carbs with graceful fallback. Appends warning to `warnings`.

    Postconditions:
      * Returns a `MacroAdjustResult` with positive macro grams.
      * If a fallback was applied, `warnings[-1]` carries an actionable
        explanation derived from the original `MacroBackAdjustFailed`.
      * `warnings` is mutated in place; the caller owns it.
    """
    result = back_adjust_macros_with_fallback(
        target_kcal=target_kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        goal=goal,
        max_iter=max_iter,
        tolerance=tolerance,
    )
    if result.warning is not None:
        warnings.append(result.warning)
    return result
