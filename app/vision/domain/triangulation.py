"""Triangulation engine — independent estimates that catch each other's lies.

(Fase 2 del Motor de Triangulación, 2026-06-11.)

A single estimator (the LLM) fails silently: a wrong answer looks exactly
like a right one. Measurement systems solve this with INDEPENDENT paths
whose errors don't correlate:

  A. Bottom-up — the existing pipeline (LLM components + DB grounding +
     hidden rules). Arrives here as `item.kcal`.
  B. Top-down — the dish matched against the NOVA recipe catalog:
     recipe.kcal × (estimated grams / recipe grams). Independent of A
     because it never looks at the LLM's per-component math.
  C. Physical plausibility — kcal/g density bands per food group. A
     400 g plate cannot hold 1800 kcal unless it is nearly pure fat;
     2 kcal for 300 g of stew is equally impossible. Free arithmetic.

The arbiter:
  - A and B agree (within AGREEMENT_PCT) → high confidence, blend them,
    NARROW the range. Two independent paths agreeing is strong evidence.
  - They disagree → C votes: whichever falls inside the plausibility
    band wins; if both do, keep A but WIDEN the range honestly.
  - C always bounds the final value: estimates outside the hard band are
    pulled to its edge (the physics override any model).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from app.vision.domain.entities import DetectedFoodItem

# kcal per gram bands by food_group: (soft_min, soft_max). Sources: USDA
# energy-density ranges for prepared foods; deliberately WIDE — these are
# physics rails, not preferences. Only "fat" approaches ethanol/lipid
# density (9 kcal/g).
DENSITY_BANDS: Final[dict[str, tuple[float, float]]] = {
    "vegetable": (0.10, 1.20),
    "fruit": (0.25, 1.50),
    "grain": (0.70, 4.00),
    "protein": (0.80, 4.50),
    "dairy": (0.30, 4.50),
    "fat": (3.00, 9.00),
    "sweet": (1.50, 6.00),
    "beverage": (0.00, 3.00),
    "other": (0.10, 6.00),
}

AGREEMENT_PCT: Final[float] = 0.25  # A vs B within ±25% = agreement
NARROW_PCT: Final[float] = 0.12     # agreed → range ±12%
WIDEN_PCT: Final[float] = 0.35      # unresolved disagreement → range ±35%
# Top-down anchor only trusted when the recipe-name match is strong AND
# the recipe has component grams to scale by.
MIN_ANCHOR_SIMILARITY: Final[float] = 0.45


def plausibility_band(item: DetectedFoodItem) -> tuple[int, int]:
    """Physically possible kcal range for this item's grams + food group."""
    lo, hi = DENSITY_BANDS.get(item.food_group or "other", DENSITY_BANDS["other"])
    grams = max(1.0, float(item.estimated_amount_g))
    return int(grams * lo), int(round(grams * hi))


def clamp_to_physics(item: DetectedFoodItem) -> DetectedFoodItem:
    """Hard rail: pull kcal inside the physically possible band. Fires on
    gross violations only (the bands are wide by design)."""
    lo, hi = plausibility_band(item)
    if lo <= item.kcal <= hi:
        return item
    corrected = min(max(item.kcal, lo), hi)
    # Re-bracket the range INSIDE the physics band — keeping a stale
    # kcal_max above the ceiling would leak the impossible value back
    # into the plate totals.
    prev_min = item.kcal_min if item.kcal_min is not None else corrected
    prev_max = item.kcal_max if item.kcal_max is not None else corrected
    return replace(
        item,
        kcal=corrected,
        kcal_min=max(lo, min(prev_min, corrected)),
        kcal_max=min(hi, max(prev_max, corrected)),
    )


@dataclass(slots=True, frozen=True)
class DishAnchor:
    """Top-down estimate from the recipe catalog for a main item."""

    recipe_kcal: int
    recipe_grams: float
    similarity: float

    def scaled_kcal(self, grams: float) -> int | None:
        if self.recipe_grams <= 0 or self.recipe_kcal <= 0:
            return None
        return int(round(self.recipe_kcal * grams / self.recipe_grams))


def arbitrate(
    item: DetectedFoodItem, anchor: DishAnchor | None
) -> DetectedFoodItem:
    """Reconcile bottom-up (item.kcal) with top-down (anchor) under the
    physics rails. Returns the item with final kcal + honest range."""
    item = clamp_to_physics(item)
    if anchor is None or anchor.similarity < MIN_ANCHOR_SIMILARITY:
        return item
    top_down = anchor.scaled_kcal(float(item.estimated_amount_g))
    if top_down is None or top_down <= 0:
        return item

    bottom_up = item.kcal
    lo_band, hi_band = plausibility_band(item)
    rel_gap = abs(top_down - bottom_up) / max(bottom_up, 1)

    if rel_gap <= AGREEMENT_PCT:
        # Two independent paths agree → blend (catalog weighs more: its
        # composition is audited) and narrow the range.
        blended = int(round(0.4 * bottom_up + 0.6 * top_down))
        return replace(
            item,
            kcal=blended,
            kcal_min=int(round(blended * (1 - NARROW_PCT))),
            kcal_max=int(round(blended * (1 + NARROW_PCT))),
        )

    # Disagreement → physics votes.
    bu_ok = lo_band <= bottom_up <= hi_band
    td_ok = lo_band <= top_down <= hi_band
    if td_ok and not bu_ok:
        return replace(
            item,
            kcal=top_down,
            kcal_min=int(round(top_down * (1 - WIDEN_PCT))),
            kcal_max=int(round(top_down * (1 + WIDEN_PCT))),
        )
    if bu_ok and not td_ok:
        return item  # bottom-up stands; anchor was a bad match
    # Both plausible but far apart → keep bottom-up, widen honestly to
    # cover the disagreement instead of faking certainty.
    span_lo = min(bottom_up, top_down)
    span_hi = max(bottom_up, top_down)
    cur_min = item.kcal_min if item.kcal_min is not None else bottom_up
    cur_max = item.kcal_max if item.kcal_max is not None else bottom_up
    return replace(
        item,
        kcal_min=min(int(round(span_lo * 0.9)), cur_min),
        kcal_max=max(int(round(span_hi * 1.1)), cur_max),
    )
