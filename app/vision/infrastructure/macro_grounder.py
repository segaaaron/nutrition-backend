"""Infrastructure — macro grounding for vision-detected food items.

Responsibility: take items whose `matched_food_id` has been set by the
catalog matcher and replace the LLM-estimated macros with audited per-100g
values from the `foods` table.  Unmatched items fall back to USDA FDC API
then static per-group averages.

This module must never be imported by the domain layer.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import unicodedata
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.vision.domain.entities import DetectedFoodItem

if TYPE_CHECKING:
    pass

log = get_logger("vision.macro_grounder")

# ---------------------------------------------------------------------------
# Local USDA JSON index (73 LATAM foods, deterministic, no network)
# ---------------------------------------------------------------------------

# Prep methods that do NOT materially change kcal/100g are stopwords (they only
# add water weight or are cosmetic). Frying is deliberately NOT here: it adds
# absorbed oil (~60-90 kcal/100g), so "papas fritas" must not collapse to raw
# "papa". Keeping "frit*" as a distinguishing token lets fried variants win.
_STOPWORDS: frozenset[str] = frozenset({
    "de", "en", "al", "con", "y", "el", "la", "los", "las", "un", "una", "del",
    "sin", "grasa", "natural", "a",
    "crudo", "cruda", "crudos", "crudas",
    "cocido", "cocida", "cocidos", "cocidas",
    "asado", "asada", "asados", "asadas",
    "hervido", "hervida",
    "horno", "vapor", "plancha", "salteado", "salteada",
    "relleno", "rellena", "fresco", "fresca",
    "magro", "magra", "bajo", "baja", "entero", "entera",
})

# Overlap fraction of key tokens that must appear in query to accept a match.
# 0.67 allows "lomo de res" (2/3 key tokens) while rejecting weak partial hits.
_LOCAL_USDA_THRESHOLD = 0.67


def _deaccent(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _stem(t: str) -> str:
    """Minimal Spanish plural stem: remove trailing 'es' or 's'."""
    if len(t) > 4 and t.endswith("es"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s"):
        return t[:-1]
    return t


def _key_tokens(s: str) -> frozenset[str]:
    base = s.split("(")[0]
    normed = _deaccent(base.lower())
    return frozenset(_stem(t) for t in normed.split() if t not in _STOPWORDS and len(t) > 2)


def _load_local_usda() -> dict[str, tuple[frozenset[str], dict[str, Any]]]:
    path = pathlib.Path(__file__).parents[3] / "data" / "usda" / "usda_ingredient_reference.json"
    try:
        raw: dict[str, dict[str, Any]] = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 — OK4: JSON parse is best-effort; returns empty index on any file/parse error
        return {}
    return {name: (_key_tokens(name), val) for name, val in raw.items()}


_LOCAL_USDA_INDEX: dict[str, tuple[frozenset[str], dict[str, Any]]] = _load_local_usda()

# Manual EN→ES query bridge for food names the LLM may return in English.
# Maps lowercase English name → Spanish query string that matches the USDA index.
_MANUAL_EN_TO_ES: dict[str, str] = {
    # proteins
    "chicken": "pechuga pollo",
    "chicken breast": "pechuga pollo",
    "grilled chicken": "pechuga pollo",
    "beef": "lomo res",
    "steak": "lomo res",
    "pork": "lomo cerdo",
    "turkey": "pavo pechuga",
    "turkey breast": "pavo pechuga",
    "cod": "bacalao",
    "white fish": "bacalao",
    "salmon": "salmon",
    "shrimp": "camaron",
    "prawns": "camaron",
    "tuna": "atun",
    "egg": "huevo entero",
    "eggs": "huevo entero",
    "fried egg": "huevo frito",
    "boiled egg": "huevo cocido",
    # grains
    "oats": "avena",
    "oatmeal": "avena",
    "rolled oats": "avena",
    "porridge": "porridge avena",
    "rice": "arroz blanco cocido",
    "white rice": "arroz blanco cocido",
    "brown rice": "arroz integral cocido",
    "pasta": "pasta espagueti cocida",
    "bread": "pan molde blanco",
    "quinoa": "quinoa",
    # vegetables
    "potato": "papa",
    "potatoes": "papa",
    "sweet potato": "camote",
    "yam": "camote",
    "broccoli": "brocoli",
    "spinach": "espinacas",
    "asparagus": "esparragos",
    "lettuce": "lechuga",
    "carrot": "zanahoria",
    "tomato": "tomate",
    "onion": "cebolla",
    "mushroom": "champiñon",
    "mushrooms": "champiñon",
    "green beans": "ejotes",
    "corn": "maiz cocido",
    "cucumber": "pepino",
    "zucchini": "calabacin",
    # fruits
    "apple": "manzana",
    "banana": "platano",
    "avocado": "aguacate",
    "strawberry": "fresa",
    "strawberries": "fresa",
    "mango": "mango",
    "orange": "naranja",
    "cranberries": "arandanos",
    "dried cranberries": "arandanos",
    "blueberries": "arandanos",
    "grapes": "uvas",
    "melon": "melon",
    # dairy
    "cheese": "queso fresco",
    "cottage cheese": "queso fresco",
    "yogurt": "yogur natural",
    "yoghurt": "yogur natural",
    "milk": "leche entera",
    # fats / nuts
    "almonds": "almendras",
    "walnuts": "nueces",
    "walnut": "nueces",
    "cashews": "marañon",
    "peanut butter": "mantequilla mani",
    "olive oil": "aceite oliva",
    # legumes
    "beans": "frijoles negros",
    "black beans": "frijoles negros",
    "lentils": "lentejas",
    "chickpeas": "garbanzo",
    "peas": "arvejas",
}


def _score_index(query_tokens: frozenset[str]) -> tuple[float, dict[str, Any] | None]:
    """Return (best_score, best_entry) across the local USDA index.

    Score is one-sided key coverage ``|key∩query| / |key|`` (kept as the
    threshold metric). Ties are broken deterministically toward the MORE
    SPECIFIC match — the larger intersection size — so e.g. "chuleta de cerdo"
    ({chuleta, cerdo}) prefers "Chuleta de cerdo" (2 shared tokens) over a
    generic "Cerdo (tamale)" entry (1 shared token) that would otherwise win
    the tie by dict insertion order. Absolute overlap count also guards against
    single-token keys hijacking multi-token queries (fried-rice vs plain rice).
    """
    best_score = 0.0
    best_overlap = 0
    best_entry: dict[str, Any] | None = None
    for _key_name, (key_toks, entry) in _LOCAL_USDA_INDEX.items():
        if not key_toks:
            continue
        inter = len(key_toks & query_tokens)
        if inter == 0:
            continue
        score = inter / len(key_toks)
        # Prefer higher coverage; on a coverage tie prefer the larger
        # intersection (the more specific, multi-token match).
        if score > best_score or (score == best_score and inter > best_overlap):
            best_score = score
            best_overlap = inter
            best_entry = entry
    return best_score, best_entry


def _local_usda_lookup(name: str) -> dict[str, Any] | None:
    """Match food name to local USDA reference (token overlap ≥ _LOCAL_USDA_THRESHOLD on key side).

    Falls back to EN→ES bridge when direct Spanish lookup scores below threshold.
    """
    if not _LOCAL_USDA_INDEX:
        return None

    # 1. Direct lookup
    query_tokens = _key_tokens(name)
    if query_tokens:
        best_score, best_entry = _score_index(query_tokens)
        if best_score >= _LOCAL_USDA_THRESHOLD:
            return best_entry

    # 2. EN→ES manual bridge (handles English names from LLM)
    name_lower = name.lower().strip()
    es_query = _MANUAL_EN_TO_ES.get(name_lower)
    if es_query:
        es_tokens = _key_tokens(es_query)
        if es_tokens:
            best_score, best_entry = _score_index(es_tokens)
            if best_score >= _LOCAL_USDA_THRESHOLD:
                return best_entry

    return None

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
    """USDA lookup then static per-group averages for unmatched items.

    Resolution order:
      1. Local USDA JSON (73 LATAM foods, deterministic, no network).
      2. USDA FDC API search (real per-food data, concurrent fan-out).
      3. Static USDA group-average table (last resort).

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

    # --- Step 1: local USDA JSON (deterministic, no network) ---
    needs_fdc: list[DetectedFoodItem] = []
    for it in unmatched:
        local = _local_usda_lookup(it.name)
        if local and local.get("kcal", 0) > 0:
            factor = float(it.estimated_amount_g) / 100.0
            kcal_local = round(local["kcal"] * factor)
            if it.kcal <= 0 or (it.kcal / 5 <= kcal_local <= it.kcal * 5):
                it.kcal = kcal_local
                it.protein_g = round(local.get("protein_g", 0) * factor)
                it.carbs_g = round(local.get("carbs_g", 0) * factor)
                it.fat_g = round(local.get("fat_g", 0) * factor)
                it.fiber_g = round(local.get("fiber_g", 0) * factor)
                it.sugar_g = round(local.get("sugar_g", 0) * factor)
                it.kcal_min = round(kcal_local * 0.80)
                it.kcal_max = round(kcal_local * 1.20)
                it.match_method = "usda_local"
                log.info(
                    "vision.ground.local_usda",
                    name=it.name[:60],
                    kcal_local=kcal_local,
                )
                continue
            log.info(
                "vision.ground.local_usda_rejected",
                name=it.name[:60],
                kcal_llm=it.kcal,
                kcal_local=kcal_local,
            )
        needs_fdc.append(it)

    if not needs_fdc:
        return

    # --- Step 2: USDA FDC API (network, concurrent) ---
    fdc_results = await asyncio.gather(
        *[usda_fdc.search(it.name) for it in needs_fdc],
        return_exceptions=True,
    )

    for it, fdc in zip(needs_fdc, fdc_results, strict=False):
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

        # --- Step 3: static group average ---
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
