"""Plate Decomposition 2.0 — deterministic hidden-calorie rules + honest totals.

Pure domain module (no I/O). Post-processes the LLM's full-plate
decomposition (v2 prompt: every component gets a `role` and `prep_method`)
with rules the LLM cannot be trusted to apply consistently:

1. DRY-SPICE CLAMP — culinary doses of dry spices (comino, pimienta,
   orégano…) are nutritionally ~0; LLMs routinely hallucinate 20-40 kcal
   for "una pizca de comino". Clamped to ≤ DRY_SPICE_KCAL_CAP. This is
   what differentiates *especias* (≈0 kcal) from *condimentos calóricos*
   (ají en aceite, mayonesa, salsa criolla — real kcal, left untouched).

2. HIDDEN COOKING FAT — fried/sautéed items absorb oil that is invisible
   on the plate. If the decomposition contains a fried-family item but NO
   cooking_fat/sauce component, we add an inferred oil item:
   absorbed g = Σ(item_g × absorption% per prep method). Absorption
   ratios from frying literature (deep-fry 8-15% of food weight; we use
   conservative midpoints). The item is flagged `inferred=True` and gets
   confidence 0.5 — below FOOD_LOG_AUTO_INSERT_CONFIDENCE, so it surfaces
   for user review instead of silently logging.

3. HONEST TOTALS — per-item kcal ranges (LLM-provided, or derived from
   confidence when absent) aggregate into PlateTotals(kcal_min/kcal/
   kcal_max). A photo can never yield exact calories; a calibrated range
   is the elite-honest answer.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from app.vision.domain.entities import DetectedFoodItem

# ---------------------------------------------------------------------------
# Vocabulary (kept in sync with VISION_SCHEMA enums in openai_vision.py)
# ---------------------------------------------------------------------------

ITEM_ROLES: Final[frozenset[str]] = frozenset(
    {
        "main",
        "side",
        "sauce",
        "condiment",
        "cooking_fat",
        "garnish",
        "sweetener",
        "beverage_base",
    }
)

PREP_METHODS: Final[frozenset[str]] = frozenset(
    {
        "deep_fried",
        "fried",
        "sauteed",
        "grilled",
        "boiled",
        "steamed",
        "baked",
        "stewed",
        "raw",
        "unknown",
    }
)

# Oil absorbed as a fraction of the food item's weight, by prep method.
# Refs: Saguy & Dana 2003 (deep-fat frying absorption 8-15%); conservative
# midpoints so the inferred item is defensible, not alarmist.
OIL_ABSORPTION_PCT: Final[dict[str, float]] = {
    "deep_fried": 0.12,
    "fried": 0.10,
    "sauteed": 0.04,
}

OIL_KCAL_PER_G: Final[float] = 8.84  # vegetable oil, USDA FDC 171413
OIL_FAT_PER_G: Final[float] = 1.0

# Dry spices & aromatic herbs: nutritionally negligible at culinary doses.
# Lowercase, accent-stripped match (prefix match on first token too).
DRY_SPICES: Final[frozenset[str]] = frozenset(
    {
        "comino",
        "cumin",
        "pimienta",
        "pepper",
        "oregano",
        "paprika",
        "pimenton",
        "curcuma",
        "turmeric",
        "canela",
        "cinnamon",
        "clavo",
        "clove",
        "laurel",
        "bay leaf",
        "romero",
        "rosemary",
        "tomillo",
        "thyme",
        "perejil",
        "parsley",
        "cilantro",
        "coriander",
        "culantro",
        "ajo en polvo",
        "garlic powder",
        "cebolla en polvo",
        "onion powder",
        "achiote",
        "annatto",
        "aji seco",
        "aji panca seco",
        "chile en polvo",
        "chili powder",
        "nuez moscada",
        "nutmeg",
        "anis",
        "anise",
        "sal",
        "salt",
        "huacatay seco",
        "sazonador",
        "seasoning",
        "especias",
        "spices",
    }
)

DRY_SPICE_KCAL_CAP: Final[int] = 5
INFERRED_CONFIDENCE: Final[float] = 0.5

# Per-item kcal range when the LLM didn't provide one: width scales with
# how unsure the model is (high confidence → ±15%, low → ±40%).
_RANGE_BASE: Final[float] = 0.15
_RANGE_SPREAD: Final[float] = 0.25


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().strip())
    return "".join(c for c in s if not unicodedata.combining(c))


def is_dry_spice(name: str) -> bool:
    n = _norm(name)
    if n in DRY_SPICES:
        return True
    # "comino molido", "pimienta negra" — first token match.
    first = n.split()[0] if n.split() else ""
    return first in DRY_SPICES


def clamp_dry_spices(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """Cap kcal of dry spices/herbs; never touch caloric condiments.

    `role == "condiment"` alone is NOT enough to clamp: ají en aceite or
    mayonesa are condiments with real calories. Only name-matched dry
    spices are capped.
    """
    out: list[DetectedFoodItem] = []
    for it in items:
        if it.kcal > DRY_SPICE_KCAL_CAP and is_dry_spice(it.name):
            out.append(
                replace(
                    it,
                    kcal=DRY_SPICE_KCAL_CAP,
                    protein_g=0,
                    carbs_g=min(it.carbs_g, 1),
                    fat_g=0,
                    kcal_min=0,
                    kcal_max=DRY_SPICE_KCAL_CAP,
                )
            )
        else:
            out.append(it)
    return out


def infer_hidden_cooking_fat(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """Add an inferred cooking-oil item when frying is visible but fat isn't.

    Skips when the decomposition already lists any cooking_fat item or an
    oil-named component — the LLM accounted for it. The inferred item is
    flagged and low-confidence so it never auto-logs silently.
    """
    # Whole-token match (QA 2026-06-12: substring "oil" fired on
    # "bOILed egg", silently suppressing the frying-oil inference).
    def _names_fat(name: str) -> bool:
        tokens = _norm(name).replace("-", " ").split()
        return "aceite" in tokens or "oil" in tokens

    has_fat_listed = any(
        (it.role == "cooking_fat") or _names_fat(it.name) for it in items
    )
    if has_fat_listed:
        return items

    absorbed_g = 0.0
    for it in items:
        pct = OIL_ABSORPTION_PCT.get(it.prep_method or "")
        if pct:
            absorbed_g += float(it.estimated_amount_g) * pct
    if absorbed_g < 1.0:
        return items

    absorbed_g = round(absorbed_g, 1)
    kcal_best = int(round(absorbed_g * OIL_KCAL_PER_G))
    oil = DetectedFoodItem(
        name="aceite de cocción (estimado)",
        estimated_amount_g=Decimal(str(absorbed_g)),
        kcal=kcal_best,
        protein_g=0,
        carbs_g=0,
        fat_g=int(round(absorbed_g * OIL_FAT_PER_G)),
        confidence=INFERRED_CONFIDENCE,
        food_group="fat",
        role="cooking_fat",
        prep_method="unknown",
        kcal_min=int(round(kcal_best * 0.5)),  # cook may drain/use little oil
        kcal_max=int(round(kcal_best * 1.3)),
        inferred=True,
    )
    return [*items, oil]


# ---------------------------------------------------------------------------
# Hidden-calorie rules v2 (Fase 3, 2026-06-11) — invisible dairy/oil + LatAm
# caloric-condiment floors. All deterministic; LLM never sees these.
# ---------------------------------------------------------------------------

# Cream soups: "crema de zapallo" carries ~30 ml crema de leche per 400 g
# serving (~58 kcal) that is visually indistinguishable from the base.
_CREAM_SOUP_MARKERS: Final[tuple[str, ...]] = ("crema de", "sopa crema", "cream of")
_CREAM_KCAL_PER_400G: Final[int] = 58
_CREAM_FAT_PER_400G: Final[int] = 6

# Mashed potatoes/purées: butter is mixed in (~5 g per 200 g serving).
_PUREE_MARKERS: Final[tuple[str, ...]] = ("pure", "puree", "mashed")
_PUREE_BUTTER_KCAL_PER_200G: Final[int] = 37
_PUREE_BUTTER_FAT_PER_200G: Final[int] = 4

# LatAm rice is sautéed in oil before boiling ("arroz graneado"): ~4 g oil
# per 150 g cooked rice that the LLM usually misses on boiled-looking rice.
_RICE_MARKERS: Final[tuple[str, ...]] = ("arroz", "rice")
_RICE_OIL_KCAL_PER_150G: Final[int] = 35
_RICE_OIL_FAT_PER_150G: Final[int] = 4

# Caloric condiments the LLM tends to under-count when the blob is small.
# name marker → (min_kcal_per_typical_serving, typical_serving_g).
CALORIC_CONDIMENT_FLOORS: Final[dict[str, tuple[int, int]]] = {
    "aji en aceite": (45, 15),
    "mayonesa": (90, 12),
    "mayo": (90, 12),
    "huancaina": (55, 30),
    "chimichurri": (60, 15),
    "salsa criolla": (25, 40),
    "mantequilla": (36, 5),
    "butter": (36, 5),
    "crema de leche": (50, 25),
    "ketchup": (17, 15),
    "salsa golf": (75, 15),
}


def _scaled(base_kcal: int, base_g: int, actual_g: float) -> int:
    return int(round(base_kcal * max(actual_g, 1.0) / base_g))


def infer_hidden_dairy_and_oil(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """v2 invisible components: cream in cream-soups, butter in purées,
    sautéed-in oil in LatAm rice. Each only fires when no item already
    accounts for it; inferred items are flagged + low-confidence so they
    surface for review instead of silently logging."""
    has_dairy_fat = any(
        it.role == "cooking_fat"
        or it.food_group in ("dairy", "fat")
        for it in items
    )
    out = list(items)
    for it in items:
        n = _norm(it.name)
        grams = float(it.estimated_amount_g)
        if any(m in n for m in _CREAM_SOUP_MARKERS) and not has_dairy_fat:
            kcal = _scaled(_CREAM_KCAL_PER_400G, 400, grams)
            out.append(
                DetectedFoodItem(
                    name="crema de leche en la sopa (estimado)",
                    estimated_amount_g=Decimal(str(round(grams * 30 / 400, 1))),
                    kcal=kcal,
                    protein_g=0,
                    carbs_g=1,
                    fat_g=_scaled(_CREAM_FAT_PER_400G, 400, grams),
                    confidence=INFERRED_CONFIDENCE,
                    food_group="dairy",
                    role="sauce",
                    prep_method="unknown",
                    kcal_min=0,
                    kcal_max=int(kcal * 1.5),
                    inferred=True,
                )
            )
            has_dairy_fat = True
        elif any(m in n for m in _PUREE_MARKERS) and not has_dairy_fat:
            kcal = _scaled(_PUREE_BUTTER_KCAL_PER_200G, 200, grams)
            out.append(
                DetectedFoodItem(
                    name="mantequilla en el puré (estimado)",
                    estimated_amount_g=Decimal(str(round(grams * 5 / 200, 1))),
                    kcal=kcal,
                    protein_g=0,
                    carbs_g=0,
                    fat_g=_scaled(_PUREE_BUTTER_FAT_PER_200G, 200, grams),
                    confidence=INFERRED_CONFIDENCE,
                    food_group="fat",
                    role="cooking_fat",
                    prep_method="unknown",
                    kcal_min=0,
                    kcal_max=int(kcal * 1.5),
                    inferred=True,
                )
            )
            has_dairy_fat = True
        elif (
            any(n.startswith(m) or f" {m}" in n for m in _RICE_MARKERS)
            and it.prep_method in ("boiled", "steamed", "unknown", None)
            and not any(x.role == "cooking_fat" for x in out)
        ):
            kcal = _scaled(_RICE_OIL_KCAL_PER_150G, 150, grams)
            out.append(
                DetectedFoodItem(
                    name="aceite del arroz graneado (estimado)",
                    estimated_amount_g=Decimal(str(round(grams * 4 / 150, 1))),
                    kcal=kcal,
                    protein_g=0,
                    carbs_g=0,
                    fat_g=_scaled(_RICE_OIL_FAT_PER_150G, 150, grams),
                    confidence=INFERRED_CONFIDENCE,
                    food_group="fat",
                    role="cooking_fat",
                    prep_method="unknown",
                    kcal_min=0,
                    kcal_max=int(kcal * 1.5),
                    inferred=True,
                )
            )
    return out


def floor_caloric_condiments(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """Raise implausibly-low kcal on known caloric condiments. The LLM sees
    'una cucharada de mayonesa' and sometimes emits 5 kcal; the floor is
    the typical-serving value scaled to the estimated grams."""
    out: list[DetectedFoodItem] = []
    for it in items:
        n = _norm(it.name)
        floor_hit = None
        for marker, (kcal_serv, serv_g) in CALORIC_CONDIMENT_FLOORS.items():
            if marker in n and not is_dry_spice(it.name):
                grams = float(it.estimated_amount_g) or serv_g
                floor_kcal = int(round(kcal_serv * grams / serv_g))
                if it.kcal < floor_kcal:
                    floor_hit = floor_kcal
                break
        if floor_hit is not None:
            out.append(
                replace(
                    it,
                    kcal=floor_hit,
                    kcal_min=int(round(floor_hit * 0.7)),
                    kcal_max=int(round(floor_hit * 1.4)),
                )
            )
        else:
            out.append(it)
    return out


@dataclass(slots=True, frozen=True)
class PlateTotals:
    kcal_min: int
    kcal: int
    kcal_max: int
    protein_g: int
    carbs_g: int
    fat_g: int
    confidence: float  # amount-weighted mean of item confidences


def _item_range(it: DetectedFoodItem) -> tuple[int, int]:
    if it.kcal_min is not None and it.kcal_max is not None:
        lo, hi = int(it.kcal_min), int(it.kcal_max)
    else:
        width = _RANGE_BASE + _RANGE_SPREAD * (1.0 - max(0.0, min(1.0, it.confidence)))
        lo = int(round(it.kcal * (1.0 - width)))
        hi = int(round(it.kcal * (1.0 + width)))
    # Sanity: range must bracket the best estimate.
    return min(lo, it.kcal), max(hi, it.kcal)


def compute_totals(items: list[DetectedFoodItem]) -> PlateTotals:
    if not items:
        return PlateTotals(0, 0, 0, 0, 0, 0, 0.0)
    kcal_min = kcal_max = 0
    for it in items:
        lo, hi = _item_range(it)
        kcal_min += lo
        kcal_max += hi
    total_g = sum(float(it.estimated_amount_g) for it in items) or 1.0
    weighted_conf = sum(
        it.confidence * float(it.estimated_amount_g) for it in items
    ) / total_g
    return PlateTotals(
        kcal_min=kcal_min,
        kcal=sum(it.kcal for it in items),
        kcal_max=kcal_max,
        protein_g=sum(it.protein_g for it in items),
        carbs_g=sum(it.carbs_g for it in items),
        fat_g=sum(it.fat_g for it in items),
        confidence=round(weighted_conf, 3),
    )


def decompose(items: list[DetectedFoodItem]) -> tuple[list[DetectedFoodItem], PlateTotals]:
    """Full post-pass: spice clamp → condiment floors → hidden fat (fry) →
    hidden dairy/oil v2 (cream soups, purées, LatAm rice) → beverage
    refinement (container snap + curated table + alcohol formula) → totals."""
    from app.vision.domain.beverage_engine import refine_beverages

    out = clamp_dry_spices(items)
    out = floor_caloric_condiments(out)
    out = infer_hidden_cooking_fat(out)
    out = infer_hidden_dairy_and_oil(out)
    out = refine_beverages(out)
    return out, compute_totals(out)
