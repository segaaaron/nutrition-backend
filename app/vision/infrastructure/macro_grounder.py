"""Infrastructure — macro grounding for vision-detected food items.

Responsibility: take items whose `matched_food_id` has been set by the
catalog matcher and replace the LLM-estimated macros with audited per-100g
values from the `foods` table.  Unmatched items fall back to USDA FDC API
then static per-group averages.

This module must never be imported by the domain layer.
"""
from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.vision.domain.entities import DetectedFoodItem

if TYPE_CHECKING:
    pass

log = get_logger("vision.macro_grounder")

# USDA FDC SR Legacy averages per 100 g by food_group.
# Tuple: (kcal, protein_g, carbs_g, fat_g)
USDA_FALLBACK_PER_100G: dict[str, tuple[int, int, int, int]] = {
    "protein":   (165, 25,  0,  7),
    "grain":     (350,  8, 72,  3),
    "vegetable": ( 35,  2,  7,  0),
    "fruit":     ( 60,  1, 15,  0),
    "dairy":     (150,  8, 12,  8),
    "fat":       (720,  0,  0, 80),
    "sweet":     (400,  2, 92,  5),
    "beverage":  ( 45,  0, 11,  0),
    "other":     (150,  5, 20,  5),
}


async def ground_macros_from_db(
    items: list[DetectedFoodItem], *, session: AsyncSession
) -> None:
    """Recompute macros from `foods` table for catalog-matched items.

    Batches one SELECT for all matched food IDs. Applies Decimal banker's
    rounding.  Skips items whose DB kcal disagrees with LLM estimate by >2×
    (signals a wrong match, not a wrong estimate).
    """
    matched = [it for it in items if it.matched_food_id is not None]
    if not matched:
        return

    ids = list({str(it.matched_food_id) for it in matched})
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id,
                           COALESCE(kcal, 0),
                           COALESCE(protein_g, 0),
                           COALESCE(carbs_g, 0),
                           COALESCE(fat_g, 0)
                      FROM foods
                     WHERE id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"ids": ids},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 — OK4: grounding is best-effort; LLM estimates remain
        log.warning("vision.ground.lookup_failed", err=str(exc))
        return

    per100: dict[str, tuple[int, int, int, int]] = {
        row[0]: (row[1], row[2], row[3], row[4]) for row in rows
    }

    for it in matched:
        macro = per100.get(str(it.matched_food_id))
        if macro is None or not macro[0]:
            continue

        factor = Decimal(str(it.estimated_amount_g)) / Decimal("100")

        def _scale(v: object, _f: Decimal = factor) -> int:
            return int(
                (Decimal(str(v)) * _f).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            )

        kcal_db = _scale(macro[0])
        if kcal_db <= 0:
            continue
        if it.kcal > 0 and not (it.kcal / 2 <= kcal_db <= it.kcal * 2):
            log.info(
                "vision.ground.match_disagreement",
                name=it.name[:60],
                kcal_llm=it.kcal,
                kcal_db=kcal_db,
                method=it.match_method,
            )
            continue

        it.kcal = kcal_db
        it.protein_g = _scale(macro[1])
        it.carbs_g = _scale(macro[2])
        it.fat_g = _scale(macro[3])
        it.kcal_min = int(round(kcal_db * 0.8))
        it.kcal_max = int(round(kcal_db * 1.2))


# Gross-incoherence guard threshold. USDA/catalog kcal uses food-specific
# Atwater factors (not a flat 4/4/9), so small deviations from 4·p+4·c+9·f are
# EXPECTED and must be preserved — a tight threshold would wrongly overwrite
# curated USDA kcal. Only a gap this large signals a real defect (corrupt source
# row, or a scaling/count bug that touched kcal but not the macros), never the
# normal Atwater-factor nuance. 40% is deliberately loose for that reason.
_GROSS_INCOHERENCE_THRESHOLD = 0.40


def reconcile_kcal_atwater(items: list[DetectedFoodItem]) -> None:
    """Final coherence guard: run AFTER grounding on every item.

    Post-grounding, kcal and macros come from the same trusted source (catalog
    `foods` row or USDA FDC), so they are already internally consistent and the
    small kcal ≠ 4·p+4·c+9·f gap from food-specific Atwater factors is left
    UNTOUCHED — overriding it would degrade USDA's curated calories.

    This only repairs GROSS drift (> `_GROSS_INCOHERENCE_THRESHOLD`), which can
    only come from a corrupt source or a pipeline bug (e.g. `count` multiplied
    into kcal but not the macros). In that case the macros are the reliable
    anchor, so kcal is recomputed from them via Atwater and the ±20% band reset.
    Generic: applies to any food, not one dish."""
    for it in items:
        macro_kcal = it.protein_g * 4 + it.carbs_g * 4 + it.fat_g * 9
        if macro_kcal <= 0 or it.kcal <= 0:
            # Zero-macro foods (water, pure spices) or unset kcal: nothing to
            # reconcile — trust whatever grounding/parse already set.
            continue
        discrepancy = abs(it.kcal - macro_kcal) / max(it.kcal, macro_kcal)
        if discrepancy <= _GROSS_INCOHERENCE_THRESHOLD:
            continue
        log.info(
            "vision.ground.atwater_reconcile",
            name=it.name[:60],
            kcal_before=it.kcal,
            kcal_after=macro_kcal,
            method=it.match_method,
        )
        it.kcal = macro_kcal
        it.kcal_min = int(round(macro_kcal * 0.80))
        it.kcal_max = int(round(macro_kcal * 1.20))


async def apply_group_fallback(items: list[DetectedFoodItem]) -> None:
    """USDA FDC API lookup then static per-group averages for unmatched items.

    Resolution order:
      1. USDA FDC API search (real per-food data, concurrent fan-out).
      2. Static USDA group-average table (last resort).

    A >5× gap between fallback kcal and LLM estimate signals a wrong
    food_group; trusts the LLM value in that case.
    """
    from app.vision.infrastructure import usda_fdc  # late import: avoids circular

    unmatched = [
        it for it in items
        if it.matched_food_id is None
        and not it.inferred
        and float(it.estimated_amount_g) > 0
    ]
    if not unmatched:
        return

    fdc_results = await asyncio.gather(
        *[usda_fdc.search(it.name) for it in unmatched],
        return_exceptions=True,
    )

    for it, fdc in zip(unmatched, fdc_results, strict=False):
        factor = float(it.estimated_amount_g) / 100.0

        if isinstance(fdc, BaseException):
            fdc = None

        if fdc is not None and fdc.kcal_per_100g > 0:
            kcal_fb = round(fdc.kcal_per_100g * factor)
            if it.kcal <= 0 or (it.kcal / 5 <= kcal_fb <= it.kcal * 5):
                it.kcal = kcal_fb
                it.protein_g = round(fdc.protein_per_100g * factor)
                it.carbs_g = round(fdc.carbs_per_100g * factor)
                it.fat_g = round(fdc.fat_per_100g * factor)
                it.fiber_g = round(fdc.fiber_per_100g * factor)
                it.sugar_g = round(fdc.sugar_per_100g * factor)
                it.kcal_min = round(kcal_fb * 0.80)
                it.kcal_max = round(kcal_fb * 1.20)
                it.match_method = "usda_fdc"
                continue

        group = it.food_group or "other"
        macro = USDA_FALLBACK_PER_100G.get(group, USDA_FALLBACK_PER_100G["other"])
        kcal_fb = round(macro[0] * factor)
        if it.kcal > 0 and not (it.kcal / 5 <= kcal_fb <= it.kcal * 5):
            continue

        it.kcal = kcal_fb
        it.protein_g = round(macro[1] * factor)
        it.carbs_g = round(macro[2] * factor)
        it.fat_g = round(macro[3] * factor)
        it.kcal_min = round(kcal_fb * 0.75)
        it.kcal_max = round(kcal_fb * 1.25)
        it.match_method = "group_fallback"
        log.info(
            "vision.ground.group_fallback",
            name=it.name[:60],
            food_group=group,
            kcal_fb=kcal_fb,
        )
