"""USDA FoodData Central API client.

Fallback nutrition source for food items not matched in the local catalog.
Free API — 3,500 req/hour anonymous, unlimited with key.
Key: https://fdc.nal.usda.gov/api-guide.html

Resolution order in the vision pipeline:
  1. Local catalog (trigram/embedding) → grounded from foods DB
  2. USDA FDC search (this module) → scales per-100g to estimated grams
  3. USDA group-average fallback → _USDA_FALLBACK_PER_100G table

The caller (process_vision_job._apply_group_fallback) invokes this before
falling back to the static table so real nutrition data is used whenever
the USDA API can match the food.

Name translation:
  USDA FDC is English-only. Food names from the LLM arrive in Spanish.
  A lightweight normalisation (accent-strip + common-word dict) converts
  the name before searching. This is intentionally small — the goal is a
  best-effort lookup, not perfect translation.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("vision.usda_fdc")

_USDA_BASE = "https://api.nal.usda.gov/fdc/v1"
_TIMEOUT_S = 4.0
# Prefer Foundation + SR Legacy — most complete nutrient coverage.
_DATA_TYPES = "Foundation,SR Legacy"

# Shared client — reuses TCP connections across calls within the same event loop.
# Avoids opening a new connection per food item (critical: plates have 5-10 items).
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client  # noqa: PLW0603 — module-level singleton; reset only in tests
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT_S)
    return _client


# Common Spanish → English food word map for LATAM staples.
# IMPORTANT: multi-word phrases MUST appear before their single-word components
# so longer matches fire first. _translate() sorts by key length desc — do NOT
# rely on dict insertion order for correctness.
_ES_TO_EN: dict[str, str] = {
    "platano maduro": "ripe plantain",
    "camote": "sweet potato",
    "a la plancha": "grilled",
    "al horno": "baked",
    "pollo": "chicken",
    "res": "beef",
    "cerdo": "pork",
    "carne": "meat",
    "pescado": "fish",
    "atun": "tuna",
    "salmon": "salmon",
    "camaron": "shrimp",
    "huevo": "egg",
    "leche": "milk",
    "queso": "cheese",
    "yogur": "yogurt",
    "arroz": "rice",
    "frijol": "bean",
    "lenteja": "lentil",
    "papa": "potato",
    "yuca": "cassava",
    "platano": "plantain",
    "maiz": "corn",
    "tortilla": "tortilla",
    "pan": "bread",
    "avena": "oatmeal",
    "zanahoria": "carrot",
    "brocoli": "broccoli",
    "espinaca": "spinach",
    "tomate": "tomato",
    "cebolla": "onion",
    "ajo": "garlic",
    "aguacate": "avocado",
    "mango": "mango",
    "naranja": "orange",
    "manzana": "apple",
    "aceite": "oil",
    "mantequilla": "butter",
    "crema": "cream",
    "mayonesa": "mayonnaise",
    "azucar": "sugar",
    "sal": "salt",
    "frito": "fried",
    "cocido": "cooked",
    "asado": "roasted",
    "hervido": "boiled",
    "vapor": "steamed",
    "revuelto": "scrambled",
    "sopa": "soup",
    "ensalada": "salad",
    "guiso": "stew",
}

# Pre-sort by key length descending so multi-word phrases match before their parts.
_ES_TO_EN_SORTED: list[tuple[str, str]] = sorted(
    _ES_TO_EN.items(), key=lambda kv: len(kv[0]), reverse=True
)


def _translate(name: str) -> str:
    """Best-effort Spanish → English for USDA search.

    Applies longest-match-first to avoid single words shadowing multi-word phrases
    (e.g. 'platano' must not replace before 'platano maduro' is tried).
    """
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for es, en in _ES_TO_EN_SORTED:
        s = re.sub(rf"\b{re.escape(es)}\b", en, s)
    return s.strip()


@dataclass(frozen=True, slots=True)
class UsdaNutrition:
    kcal_per_100g: float
    protein_per_100g: float
    carbs_per_100g: float
    fat_per_100g: float
    fiber_per_100g: float
    sugar_per_100g: float
    fdc_id: int
    description: str


async def search(name: str) -> UsdaNutrition | None:
    """Search USDA FDC for a food name, return per-100g macros or None.

    Fail-open: any network/parse error returns None so the pipeline
    falls through to the static group-average table.
    """
    api_key = get_settings().usda_fdc_api_key
    query = _translate(name)
    if not query:
        return None

    params: dict[str, Any] = {
        "query": query,
        "dataType": _DATA_TYPES,
        "pageSize": 1,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        resp = await _get_client().get(f"{_USDA_BASE}/foods/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — fail-open by contract
        log.debug("vision.usda_fdc.request_failed", err=str(exc)[:120], query=query)
        return None

    foods = data.get("foods") or []
    if not foods:
        log.debug("vision.usda_fdc.no_results", query=query, name=name[:60])
        return None

    food = foods[0]
    nutrients = {n["nutrientName"]: n.get("value", 0.0) for n in food.get("foodNutrients", [])}

    kcal = float(
        nutrients.get("Energy")
        or nutrients.get("Energy (Atwater General Factors)")
        or nutrients.get("Energy (Atwater Specific Factors)")
        or 0
    )
    protein = float(nutrients.get("Protein") or 0)
    carbs = float(nutrients.get("Carbohydrate, by difference") or 0)
    fat = float(nutrients.get("Total lipids (fat)") or 0)
    fiber = float(nutrients.get("Fiber, total dietary") or 0)
    sugar = float(nutrients.get("Sugars, total including NLEA") or nutrients.get("Sugars, total") or 0)

    if kcal <= 0 and (protein + carbs + fat) <= 0:
        log.debug("vision.usda_fdc.empty_nutrients", fdc_id=food.get("fdcId"), query=query)
        return None

    result = UsdaNutrition(
        kcal_per_100g=kcal,
        protein_per_100g=protein,
        carbs_per_100g=carbs,
        fat_per_100g=fat,
        fiber_per_100g=fiber,
        sugar_per_100g=sugar,
        fdc_id=int(food.get("fdcId", 0)),
        description=str(food.get("description", ""))[:120],
    )
    log.info(
        "vision.usda_fdc.match",
        name=name[:60],
        query=query,
        fdc_id=result.fdc_id,
        kcal=result.kcal_per_100g,
        description=result.description[:60],
    )
    return result
