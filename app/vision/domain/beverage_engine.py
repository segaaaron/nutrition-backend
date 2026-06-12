"""Beverage engine — exact-by-construction kcal for drinks (Fase 1, 2026-06-11).

Drinks are the one photo category where near-exact calories are achievable
TODAY, because the physics and the packaging are standardized:

1. CONTAINERS are industrial standards (lata 355 ml, botella 620 ml…).
   The LLM only needs to identify the container type; the volume comes
   from this table, not from pixel guessing. Estimated volumes within
   SNAP_TOLERANCE of a standard snap to it.

2. ALCOHOL kcal is arithmetic, not estimation: ethanol is 7 kcal/g and
   0.789 g/ml ⇒ kcal_alcohol = ABV% × ml × 0.789 × 7 / 100. A 355 ml
   5% beer is ~98 kcal of alcohol + ~13 g carbs ≈ 150 kcal — computed,
   not hallucinated.

3. BRANDED sodas/beers have label-stable composition. The LLM reads the
   brand in the photo ("Coca-Cola", "Inca Kola", "Pilsen"); this curated
   per-100ml table provides the calories. Zero/light/diet variants are
   detected by name and zeroed.

Precedence note: this engine OVERRIDES the LLM estimate (and the generic
DB grounding) for items it matches — for branded drinks and alcohol the
curated table + formula are strictly more reliable than either.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from app.vision.domain.entities import DetectedFoodItem

# --- Physics ----------------------------------------------------------------

ETHANOL_G_PER_ML: Final[float] = 0.789
KCAL_PER_G_ETHANOL: Final[float] = 7.0


def alcohol_kcal(abv_pct: float, ml: float) -> float:
    """kcal from ethanol alone: ABV% × ml × 0.789 g/ml × 7 kcal/g."""
    return abv_pct / 100.0 * ml * ETHANOL_G_PER_ML * KCAL_PER_G_ETHANOL


# --- Standard containers (ml) ------------------------------------------------
# LatAm-aware: 620 ml is the Peruvian beer bottle; 473 the "lata grande".
STANDARD_CONTAINERS_ML: Final[tuple[float, ...]] = (
    44.0,    # shot
    150.0,   # copa de vino
    200.0,   # vaso pequeño / tetrapak chico
    250.0,   # vaso estándar
    330.0,   # lata/botella chica
    355.0,   # lata estándar
    473.0,   # lata grande / pinta
    500.0,   # botella personal
    620.0,   # botella cerveza (PE)
    750.0,   # botella vino
    1000.0,  # litro
)

SNAP_TOLERANCE: Final[float] = 0.12  # ±12% → snap to the standard


def snap_to_container(ml: float) -> float:
    """Snap an estimated volume to the nearest standard container when the
    estimate is within tolerance — the LLM guessing 340 ml of a can means
    the 355 ml standard, not a custom 340 ml pour."""
    if ml <= 0:
        return ml
    best = min(STANDARD_CONTAINERS_ML, key=lambda c: abs(c - ml))
    if abs(best - ml) / best <= SNAP_TOLERANCE:
        return best
    return ml


# --- Curated beverage profiles ------------------------------------------------


@dataclass(slots=True, frozen=True)
class BeverageProfile:
    kcal_per_100ml: float
    abv_pct: float = 0.0  # >0 ⇒ alcohol formula dominates kcal
    carbs_g_per_100ml: float = 0.0
    protein_g_per_100ml: float = 0.0
    fat_g_per_100ml: float = 0.0


# Keyword → profile. Keys are accent-stripped lowercase TOKEN SEQUENCES
# matched against whole tokens of the item name (QA 2026-06-12: naive
# substring matching turned "jugo de toRONja" into RON → 552 kcal of
# alcohol on a grapefruit juice, and "chocolaTE calienTE" into TE →
# ~1 kcal). ORDER MATTERS: more specific entries (zero/light, multi-word)
# must appear before their generic parents.
_ZERO: Final[BeverageProfile] = BeverageProfile(kcal_per_100ml=0.4)

BEVERAGE_PROFILES: Final[dict[str, BeverageProfile]] = {
    # --- diet / zero variants (must match before brand generics) ---
    "zero": _ZERO,
    "light": _ZERO,
    "diet": _ZERO,
    "sin azucar": _ZERO,
    "sugar free": _ZERO,
    # --- sodas (per label, kcal/100ml) ---
    "coca": BeverageProfile(42.0, carbs_g_per_100ml=10.6),
    "inca kola": BeverageProfile(42.0, carbs_g_per_100ml=11.0),
    "pepsi": BeverageProfile(41.0, carbs_g_per_100ml=11.0),
    "sprite": BeverageProfile(37.0, carbs_g_per_100ml=9.0),
    "fanta": BeverageProfile(45.0, carbs_g_per_100ml=11.5),
    "gaseosa": BeverageProfile(42.0, carbs_g_per_100ml=10.5),
    "soda": BeverageProfile(42.0, carbs_g_per_100ml=10.5),
    "refresco": BeverageProfile(42.0, carbs_g_per_100ml=10.5),
    # --- beers (typical macro per 100ml; abv → formula) ---
    "cerveza negra": BeverageProfile(50.0, abv_pct=5.5, carbs_g_per_100ml=4.5),
    "dark beer": BeverageProfile(50.0, abv_pct=5.5, carbs_g_per_100ml=4.5),
    "stout": BeverageProfile(50.0, abv_pct=5.5, carbs_g_per_100ml=4.5),
    "cerveza": BeverageProfile(43.0, abv_pct=5.0, carbs_g_per_100ml=3.6),
    "beer": BeverageProfile(43.0, abv_pct=5.0, carbs_g_per_100ml=3.6),
    "pilsen": BeverageProfile(43.0, abv_pct=5.0, carbs_g_per_100ml=3.6),
    "cusquena": BeverageProfile(45.0, abv_pct=5.0, carbs_g_per_100ml=3.8),
    "corona": BeverageProfile(42.0, abv_pct=4.5, carbs_g_per_100ml=3.9),
    # --- wine / sparkling (es + en aliases — the LLM names items in the
    # user's locale, so both languages must match) ---
    "vino tinto": BeverageProfile(85.0, abv_pct=13.5, carbs_g_per_100ml=2.6),
    "red wine": BeverageProfile(85.0, abv_pct=13.5, carbs_g_per_100ml=2.6),
    "vino blanco": BeverageProfile(82.0, abv_pct=13.0, carbs_g_per_100ml=2.6),
    "white wine": BeverageProfile(82.0, abv_pct=13.0, carbs_g_per_100ml=2.6),
    "vino": BeverageProfile(83.0, abv_pct=13.0, carbs_g_per_100ml=2.6),
    "wine": BeverageProfile(83.0, abv_pct=13.0, carbs_g_per_100ml=2.6),
    "espumante": BeverageProfile(76.0, abv_pct=12.0, carbs_g_per_100ml=1.5),
    "sparkling wine": BeverageProfile(76.0, abv_pct=12.0, carbs_g_per_100ml=1.5),
    "prosecco": BeverageProfile(76.0, abv_pct=12.0, carbs_g_per_100ml=1.5),
    "champagne": BeverageProfile(76.0, abv_pct=12.0, carbs_g_per_100ml=1.5),
    # --- spirits: kcal comes ~entirely from the ABV formula ---
    "pisco": BeverageProfile(0.0, abv_pct=42.0),
    "ron": BeverageProfile(0.0, abv_pct=40.0),
    "rum": BeverageProfile(0.0, abv_pct=40.0),
    "whisky": BeverageProfile(0.0, abv_pct=40.0),
    "whiskey": BeverageProfile(0.0, abv_pct=40.0),
    "vodka": BeverageProfile(0.0, abv_pct=40.0),
    "tequila": BeverageProfile(0.0, abv_pct=38.0),
    "gin": BeverageProfile(0.0, abv_pct=40.0),
    "aguardiente": BeverageProfile(0.0, abv_pct=40.0),
    # --- juices / others (per 100ml; es + en aliases) ---
    "chicha morada": BeverageProfile(50.0, carbs_g_per_100ml=12.5),
    "jugo de naranja": BeverageProfile(45.0, carbs_g_per_100ml=10.4),
    "orange juice": BeverageProfile(45.0, carbs_g_per_100ml=10.4),
    "jugo": BeverageProfile(48.0, carbs_g_per_100ml=11.5),
    "juice": BeverageProfile(48.0, carbs_g_per_100ml=11.5),
    "smoothie": BeverageProfile(60.0, carbs_g_per_100ml=13.0, protein_g_per_100ml=1.0),
    "limonada": BeverageProfile(40.0, carbs_g_per_100ml=10.0),
    "lemonade": BeverageProfile(40.0, carbs_g_per_100ml=10.0),
    "leche entera": BeverageProfile(
        61.0, carbs_g_per_100ml=4.8, protein_g_per_100ml=3.3, fat_g_per_100ml=3.3
    ),
    "leche descremada": BeverageProfile(
        35.0, carbs_g_per_100ml=5.0, protein_g_per_100ml=3.4, fat_g_per_100ml=0.1
    ),
    "leche": BeverageProfile(
        61.0, carbs_g_per_100ml=4.8, protein_g_per_100ml=3.3, fat_g_per_100ml=3.3
    ),
    "whole milk": BeverageProfile(
        61.0, carbs_g_per_100ml=4.8, protein_g_per_100ml=3.3, fat_g_per_100ml=3.3
    ),
    "skim milk": BeverageProfile(
        35.0, carbs_g_per_100ml=5.0, protein_g_per_100ml=3.4, fat_g_per_100ml=0.1
    ),
    "milk": BeverageProfile(
        61.0, carbs_g_per_100ml=4.8, protein_g_per_100ml=3.3, fat_g_per_100ml=3.3
    ),
    "yogurt bebible": BeverageProfile(
        70.0, carbs_g_per_100ml=12.0, protein_g_per_100ml=3.0, fat_g_per_100ml=1.5
    ),
    "drinkable yogurt": BeverageProfile(
        70.0, carbs_g_per_100ml=12.0, protein_g_per_100ml=3.0, fat_g_per_100ml=1.5
    ),
    "chocolate caliente": BeverageProfile(
        80.0, carbs_g_per_100ml=10.0, protein_g_per_100ml=3.0, fat_g_per_100ml=3.0
    ),
    "hot chocolate": BeverageProfile(
        80.0, carbs_g_per_100ml=10.0, protein_g_per_100ml=3.0, fat_g_per_100ml=3.0
    ),
    "cafe negro": BeverageProfile(1.0),
    "black coffee": BeverageProfile(1.0),
    "mate": BeverageProfile(1.0),
    "te": BeverageProfile(1.0),
    "tea": BeverageProfile(1.0),
    "agua": BeverageProfile(0.0),
    "water": BeverageProfile(0.0),
}

# Pre-tokenized keys (computed once at import).
_PROFILE_TOKENS: Final[list[tuple[tuple[str, ...], BeverageProfile]]] = []


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().strip())
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(s: str) -> tuple[str, ...]:
    return tuple(t for t in _norm(s).replace("-", " ").split() if t)


def _contains_seq(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    span = len(needle)
    return any(haystack[i : i + span] == needle for i in range(len(haystack) - span + 1))


def match_profile(name: str) -> BeverageProfile | None:
    """Whole-token sequence match — 'ron' matches the token 'ron', never
    the substring inside 'toronja'; 'te' never fires inside 'caliente'."""
    if not _PROFILE_TOKENS:
        _PROFILE_TOKENS.extend(
            (_tokens(k), v) for k, v in BEVERAGE_PROFILES.items()
        )
    name_tokens = _tokens(name)
    for key_tokens, profile in _PROFILE_TOKENS:
        if _contains_seq(name_tokens, key_tokens):
            return profile
    return None


def _is_beverage(item: DetectedFoodItem) -> bool:
    return item.food_group == "beverage" or item.role == "beverage_base"


def refine_beverages(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """Recompute beverage kcal from container standards + curated table +
    the alcohol formula. Overrides upstream estimates for matched drinks —
    for branded/alcoholic beverages this is exact-by-construction, which
    neither the LLM nor generic per-100g grounding can beat.
    """
    out: list[DetectedFoodItem] = []
    for it in items:
        if not _is_beverage(it):
            out.append(it)
            continue
        profile = match_profile(it.name)
        if profile is None:
            out.append(it)
            continue

        ml = snap_to_container(float(it.estimated_amount_g))
        if ml <= 0:
            # No volume estimate → nothing to compute from; keep LLM values.
            out.append(it)
            continue
        base = profile.kcal_per_100ml * ml / 100.0
        if profile.abv_pct > 0:
            # Alcoholic: the label per-100ml value already includes the
            # alcohol, but some table entries run low — the ethanol
            # formula + carbs is the physical floor. Spirits (base=0)
            # resolve entirely through the formula.
            alc = alcohol_kcal(profile.abv_pct, ml)
            carbs_kcal = profile.carbs_g_per_100ml * ml / 100.0 * 4.0
            kcal_best = max(base, alc + carbs_kcal)
        else:
            # Non-alcoholic: the per-100ml label value IS the truth;
            # comparing against carbs×4 would double-guess it.
            kcal_best = base
        kcal = int(round(kcal_best))
        out.append(
            replace(
                it,
                estimated_amount_g=Decimal(str(ml)),
                kcal=kcal,
                # Macros from the profile too — zeroing protein on "leche"
                # corrupted daily protein tracking (QA 2026-06-12).
                protein_g=int(round(profile.protein_g_per_100ml * ml / 100.0)),
                carbs_g=int(round(profile.carbs_g_per_100ml * ml / 100.0)),
                fat_g=int(round(profile.fat_g_per_100ml * ml / 100.0)),
                # Container snapped + curated composition → only residual
                # uncertainty is "did they finish the glass": ±10%.
                kcal_min=int(round(kcal * 0.9)),
                kcal_max=int(round(kcal * 1.1)),
            )
        )
    return out
