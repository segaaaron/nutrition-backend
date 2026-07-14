"""USDA local JSON lookup + Open Food Facts fallback.

Resolution order in the vision pipeline:
  1. Local catalog (trigram/embedding) → grounded from foods DB
  2. Redis cache (7-day TTL, key = nova:usda:<normalised_name>)
  3. ES ingredient reference (data/usda/usda_ingredient_reference.json — 817 LATAM staples)
  4. SR Legacy local (data/usda/usda_sr_legacy_per100g.json — 7,793 entries)
  5. Open Food Facts (open API, no key, strong on packaged LATAM foods)
  6. None → caller uses group-average fallback table

No HTTP calls to USDA FDC API. Data is loaded from bundled JSON at startup.

Name translation:
  USDA SR Legacy is English-only. Food names from the LLM arrive in Spanish.
  A lightweight normalisation (accent-strip + common-word dict) converts
  the name before searching. Longest-match-first prevents partial substitutions.
  The ingredient reference is searched first using the original Spanish name.
"""

from __future__ import annotations

import dataclasses
import difflib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("vision.usda_fdc")

_OFF_BASE = "https://world.openfoodfacts.org/cgi/search.pl"
_TIMEOUT_S = 4.0
# Open Food Facts is DISABLED by default. The public endpoint is unreliable
# (frequent 503s) and every lookup already falls back to the group-average
# table, so calling it just adds ~4s of dead latency per vision scan. Re-enable
# with VISION_OFF_ENABLED=1 only if the endpoint becomes reliable again.
_OFF_ENABLED = os.getenv("VISION_OFF_ENABLED", "0") == "1"

# 7-day Redis cache — nutritional data is stable.
_REDIS_TTL_S = 86_400 * 7
_REDIS_KEY_FMT = "nova:usda:{name}"

# Path to bundled USDA data files. The worker may import this module either
# from the source tree (/app/app/...) OR from the pip-installed package
# (site-packages/app/...); only the source tree has data/ alongside it, so a
# __file__-relative path alone breaks when running from the installed package.
# Resolve against several candidates and pick the one that actually exists.
def _resolve_data_dir() -> Path:
    src_relative = Path(__file__).resolve().parent.parent.parent.parent / "data" / "usda"
    candidates = [
        (Path(os.environ["VISION_DATA_DIR"]) / "usda") if os.environ.get("VISION_DATA_DIR") else None,
        Path.cwd() / "data" / "usda",  # /app/data/usda — COPY data ./data lands here (WORKDIR /app)
        src_relative,                  # source-tree layout
    ]
    for c in candidates:
        if c is not None and (c / "usda_ingredient_reference.json").is_file():
            return c
    return src_relative  # last resort → logs ref_missing, falls back to group averages


_DATA_DIR = _resolve_data_dir()

# Shared httpx client for Open Food Facts only.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client  # noqa: PLW0603
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT_S)
    return _client


# ── Local data (lazy-loaded once on first use) ────────────────────────────────

# ingredient_reference: {es_name_norm: {kcal, protein_g, fat_g, carbs_g, ...}}
_INGREDIENT_REF: dict[str, dict[str, Any]] | None = None
# SR Legacy: list of {fdc_id, desc, kcal, protein_g, ...}
_SR_LEGACY: list[dict[str, Any]] | None = None
# Pre-normalised SR Legacy descriptions for fast token matching.
_SR_DESC_NORM: list[list[str]] | None = None  # list of token lists
# Curated ES-native ingredient tables (data/nutrition_reference/) — same source
# the recipe engine uses. ES keys → direct match (no ES→EN translation needed).
_NUTRITION_MACROS: dict[str, dict[str, Any]] | None = None  # name -> {protein_g,carbs_g,fat_g}
_NUTRITION_MICROS: dict[str, dict[str, Any]] | None = None  # name -> {fiber_g,sugar_g,...}


def _norm_str(s: str) -> str:
    """Lowercase ASCII-normalised string, punctuation → space."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _norm_key(s: str) -> str:
    """Normalize ES key: strip parenthetical suffixes, accent-strip, lowercase."""
    s = re.sub(r"\(.*?\)", "", s)  # "(cruda)" → ""
    return _norm_str(s).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in _norm_str(s).split() if len(t) > 1]


# LATAM regional ingredient synonyms → a canonical term that already exists in the
# reference tables. These are word-level dictionary equivalences (regional names
# for the SAME food), NOT nutrition guesses: the target already carries verified
# USDA/reference values — we only redirect the lookup so fewer real foods fall to
# the group-average fallback. Applied only AFTER the original name fails to
# resolve, so any food that has its own entry keeps its own values.
_SYNONYMS: dict[str, str] = {
    "palta": "aguacate",
    "frejol": "frijoles",
    "frejoles": "frijoles",
    "poroto": "frijoles",
    "porotos": "frijoles",
    "caraota": "frijoles",
    "caraotas": "frijoles",
    "churrasco": "bistec de res",
    "bife": "bistec de res",
    "tallarin": "fideos",
    "tallarines": "fideos",
    "camote": "batata",
    "boniato": "batata",
    "guineo": "platano",
    "banano": "platano",
    "arveja": "guisantes",
    "arvejas": "guisantes",
    "frutilla": "fresa",
    "frutillas": "fresas",
    "betarraga": "remolacha",
    "zapallo": "calabaza",
    "durazno": "melocoton",
    "jitomate": "tomate",
    "elote": "maiz",
}


def _apply_synonyms(key: str) -> str:
    """Replace whole-word LATAM synonyms in a normalised key. Returns the key
    unchanged when no synonym applies."""
    words = key.split()
    changed = [_SYNONYMS.get(w, w) for w in words]
    return " ".join(changed)


def _headsafe_difflib(query_key: str, keys, cutoff: float = 0.72) -> str | None:
    """difflib match that rejects candidates which drop the query's HEAD noun.

    char-level difflib (Ratcliff/Obershelp) over-weights a shared suffix, so
    'carne de hamburguesa' scores highest against 'pan de hamburguesa' (they
    share 'de hamburguesa') even though the head noun flips carne→pan. Requiring
    the query's first token to appear in the candidate is the token-based guard
    (same rationale as RapidFuzz/token_set_ratio over plain difflib) — it keeps
    'bistec'→'bistec de res' and 'carne de hamburguesa'→'carne de res' while
    blocking the carne→pan class of false match. Dependency-free."""
    toks = query_key.split()
    if not toks:
        return None
    head = toks[0]
    for cand in difflib.get_close_matches(query_key, keys, n=5, cutoff=cutoff):
        if head in cand.split():
            return cand
    return None


def _subset_match(query_key: str, keys) -> str | None:
    """Return the shortest reference key whose token set is a SUPERSET of every
    query token — i.e. the query is a more-general form of a more-specific entry
    (``bistec`` → ``bistec de res``, ``lentejas`` → ``lentejas cocidas``).

    Direction is query⊆key ONLY: a short query never gets generalised to an
    unrelated broad entry, and difflib's length penalty (which drops
    ``bistec`` vs ``bistec de res`` below the 0.72 cutoff) is bypassed."""
    qt = set(query_key.split())
    if not qt:
        return None
    best: str | None = None
    best_len = 10**6
    for k in keys:
        kt = k.split()
        if len(kt) < best_len and qt.issubset(kt):
            best, best_len = k, len(kt)
    return best


def _load_local_data() -> None:
    global _INGREDIENT_REF, _SR_LEGACY, _SR_DESC_NORM  # noqa: PLW0603
    global _NUTRITION_MACROS, _NUTRITION_MICROS  # noqa: PLW0603

    ref_path = _DATA_DIR / "usda_ingredient_reference.json"
    sr_path = _DATA_DIR / "usda_sr_legacy_per100g.json"
    nutr_dir = _DATA_DIR.parent / "nutrition_reference"
    macros_path = nutr_dir / "ingredient_macros_extra.json"
    micros_path = nutr_dir / "ingredient_nutrients.json"

    if macros_path.is_file():
        raw_m: dict[str, Any] = json.loads(macros_path.read_text(encoding="utf-8"))
        _NUTRITION_MACROS = {_norm_key(k): v for k, v in raw_m.items()}
    else:
        _NUTRITION_MACROS = {}
    if micros_path.is_file():
        raw_u: dict[str, Any] = json.loads(micros_path.read_text(encoding="utf-8"))
        _NUTRITION_MICROS = {_norm_key(k): v for k, v in raw_u.items()}
    else:
        _NUTRITION_MICROS = {}

    if ref_path.exists():
        raw: dict[str, Any] = json.loads(ref_path.read_text(encoding="utf-8"))
        _INGREDIENT_REF = {_norm_key(k): v for k, v in raw.items()}
    else:
        _INGREDIENT_REF = {}
        log.warning("vision.usda_local.ref_missing", path=str(ref_path))

    if sr_path.exists():
        _SR_LEGACY = json.loads(sr_path.read_text(encoding="utf-8"))
        _SR_DESC_NORM = [_tokens(item["desc"]) for item in _SR_LEGACY]
    else:
        _SR_LEGACY = []
        _SR_DESC_NORM = []
        log.warning("vision.usda_local.sr_missing", path=str(sr_path))


def _ensure_loaded() -> None:
    if _INGREDIENT_REF is None:
        _load_local_data()


# ── Translation dict (ES → EN for SR Legacy search) ──────────────────────────

_ES_TO_EN: dict[str, str] = {
    # --- Multi-word phrases first ---
    "platano maduro": "ripe plantain",
    "platano verde": "green plantain",
    "camote morado": "purple sweet potato",
    "a la plancha": "grilled",
    "al horno": "baked",
    "al vapor": "steamed",
    "al carbon": "charcoal grilled",
    "carne molida": "ground beef",
    "carne de res": "beef",
    "pechuga de pollo": "chicken breast",
    "muslo de pollo": "chicken thigh",
    "filete de pescado": "fish fillet",
    "jugo de naranja": "orange juice",
    "agua de coco": "coconut water",
    "leche descremada": "skim milk",
    "leche entera": "whole milk",
    "queso fresco": "fresh cheese",
    "queso panela": "panela cheese",
    "arroz integral": "brown rice",
    "arroz blanco": "white rice",
    "frijoles negros": "black beans",
    "frijoles pintos": "pinto beans",
    "frijoles refritos": "refried beans",
    "papa cocida": "boiled potato",
    "papa frita": "french fries",
    "tortilla de maiz": "corn tortilla",
    "tortilla de harina": "flour tortilla",
    "sopa de verduras": "vegetable soup",
    "ensalada verde": "green salad",
    "aceite de oliva": "olive oil",
    "aceite vegetal": "vegetable oil",
    "crema agria": "sour cream",
    "chile verde": "green chili pepper",
    "chile rojo": "red chili pepper",
    # --- Bolivia / Andes ---
    "chuño cocido": "cooked freeze-dried potato",
    "trucha del lago": "lake trout",
    # --- Paraguay ---
    "sopa paraguaya": "cornbread cheese cake",
    # --- Single words ---
    "camote": "sweet potato",
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
    "mandioca": "cassava",
    "platano": "plantain",
    "maiz": "corn",
    "elote": "corn",
    "tortilla": "tortilla",
    "pan": "bread",
    "avena": "oatmeal",
    "zanahoria": "carrot",
    "brocoli": "broccoli",
    "espinaca": "spinach",
    "tomate": "tomato",
    "jitomate": "tomato",
    "cebolla": "onion",
    "ajo": "garlic",
    "aguacate": "avocado",
    "mango": "mango",
    "naranja": "orange",
    "manzana": "apple",
    "pina": "pineapple",
    "maracuya": "passion fruit",
    "guayaba": "guava",
    "papaya": "papaya",
    "aceite": "oil",
    "mantequilla": "butter",
    "crema": "sour cream",
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
    "caldo": "broth",
    "tostada": "fried tortilla",
    "ejote": "green beans",
    "chayote": "chayote squash",
    "nopales": "cactus pads",
    "guacamole": "guacamole",
    "mole": "mole sauce",
    "piloncillo": "raw cane sugar",
    "tamarindo": "tamarind",
    "betabel": "beet",
    "calabaza": "pumpkin",
    "chile": "chili pepper",
    "cilantro": "cilantro",
    "acelga": "swiss chard",
    "pepino": "cucumber",
    "achiote": "annatto",
    "chuño": "freeze-dried potato",
    "quinoa": "quinoa",
    "quinua": "quinoa",
    "locro": "hominy stew",
    "chipa": "cheese bread",
    "mbejú": "starch flatbread",
    "surubi": "river catfish",
    "pacu": "river fish pacu",
    "tilapia": "tilapia",
    "trucha": "trout",
}

_ES_TO_EN_SORTED: list[tuple[str, str]] = sorted(
    _ES_TO_EN.items(), key=lambda kv: len(kv[0]), reverse=True
)


def _translate(name: str) -> str:
    """Best-effort Spanish → English for SR Legacy / OFF search."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for es, en in _ES_TO_EN_SORTED:
        s = re.sub(rf"\b{re.escape(es)}\b", en, s)
    return s.strip()


def _cache_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return _REDIS_KEY_FMT.format(name=s[:80])


# ── Data types ────────────────────────────────────────────────────────────────

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


# ── Redis helpers ─────────────────────────────────────────────────────────────

async def _redis_get(key: str) -> UsdaNutrition | None:
    try:
        raw = await get_redis().get(key)
        if raw:
            d = json.loads(raw)
            return UsdaNutrition(**d)
    except Exception as exc:  # noqa: BLE001  OK4: best-effort cache read
        log.debug("vision.usda.cache_read_failed", err=str(exc)[:80])
    return None


async def _redis_set(key: str, result: UsdaNutrition) -> None:
    try:
        await get_redis().setex(key, _REDIS_TTL_S, json.dumps(dataclasses.asdict(result)))
    except Exception as exc:  # noqa: BLE001  OK4: best-effort cache write
        log.debug("vision.usda.cache_write_failed", err=str(exc)[:80])


# ── Local search ──────────────────────────────────────────────────────────────

def _search_ingredient_ref(name: str) -> UsdaNutrition | None:
    """Direct ES-name lookup in usda_ingredient_reference.json (817 LATAM staples).

    Tries exact normalised match first, then difflib on the key set for minor
    spelling variations (e.g. "pechuga pollo" → "pechuga de pollo cruda").
    """
    if not _INGREDIENT_REF:
        return None

    key = _norm_key(name)

    entry = _INGREDIENT_REF.get(key)
    if entry is None:
        # Regional synonym applied BEFORE difflib (palta→aguacate). Doing it first
        # prevents difflib from grabbing a spelling-similar but unrelated food
        # (e.g. "arveja"→"avena"). Subset fuzzing is intentionally left to the
        # cooked nutrition_reference — this is the raw/dry staples table.
        alt = _apply_synonyms(key)
        lookup = alt if alt != key else key
        if alt != key:
            entry = _INGREDIENT_REF.get(alt)
    if entry is None:
        # Fuzzy match on ES keys — cheap (817 short strings), head-noun guarded.
        cand = _headsafe_difflib(lookup, _INGREDIENT_REF.keys())
        if cand is not None:
            entry = _INGREDIENT_REF[cand]

    if entry is None:
        return None

    kcal = float(entry.get("kcal") or 0)
    if kcal <= 0:
        return None

    return UsdaNutrition(
        kcal_per_100g=kcal,
        protein_per_100g=float(entry.get("protein_g") or 0),
        carbs_per_100g=float(entry.get("carbs_g") or 0),
        fat_per_100g=float(entry.get("fat_g") or 0),
        fiber_per_100g=float(entry.get("fiber_g") or 0),
        sugar_per_100g=float(entry.get("sugar_g") or 0),
        fdc_id=0,
        description=str(entry.get("usda", name))[:120],
    )


def _search_nutrition_reference(name: str) -> UsdaNutrition | None:
    """Curated ES-native ingredient table (data/nutrition_reference/) — the same
    macros/micros source the recipe engine uses. ES keys → direct/fuzzy match
    (no ES→EN translation). kcal derived via Atwater (4·prot+4·carb+9·fat)."""
    if not _NUTRITION_MACROS:
        return None
    key = _norm_key(name)
    macros = _NUTRITION_MACROS.get(key)
    if macros is None:
        sk = _subset_match(key, _NUTRITION_MACROS.keys())
        if sk is not None:
            key, macros = sk, _NUTRITION_MACROS[sk]
    if macros is None:
        # Regional synonym BEFORE original difflib (camote→batata, tallarin→
        # fideos…): the canonical word is tried exact→subset→difflib first, so a
        # spelling-similar wrong food (camote→chayote) can't win.
        alt = _apply_synonyms(key)
        if alt != key:
            macros = _NUTRITION_MACROS.get(alt)
            if macros is not None:
                key = alt
            else:
                sk = _subset_match(alt, _NUTRITION_MACROS.keys())
                if sk is not None:
                    key, macros = sk, _NUTRITION_MACROS[sk]
                else:
                    cand = _headsafe_difflib(alt, _NUTRITION_MACROS.keys())
                    if cand is not None:
                        key, macros = cand, _NUTRITION_MACROS[cand]
    if macros is None:
        cand = _headsafe_difflib(key, _NUTRITION_MACROS.keys())
        if cand is not None:
            key = cand
            macros = _NUTRITION_MACROS[key]
    if macros is None:
        return None
    protein = float(macros.get("protein_g") or 0)
    carbs = float(macros.get("carbs_g") or 0)
    fat = float(macros.get("fat_g") or 0)
    kcal = 4.0 * protein + 4.0 * carbs + 9.0 * fat
    if kcal <= 0:
        return None
    micros = (_NUTRITION_MICROS or {}).get(key) or {}
    return UsdaNutrition(
        kcal_per_100g=kcal,
        protein_per_100g=protein,
        carbs_per_100g=carbs,
        fat_per_100g=fat,
        fiber_per_100g=float(micros.get("fiber_g") or 0),
        sugar_per_100g=float(micros.get("sugar_g") or 0),
        fdc_id=0,
        description=f"nutrition_reference:{name}"[:120],
    )


def _token_recall(query_toks: list[str], desc_toks: list[str]) -> float:
    """Fraction of query tokens found in desc tokens (recall score)."""
    if not query_toks:
        return 0.0
    desc_set = set(desc_toks)
    return sum(1 for t in query_toks if t in desc_set) / len(query_toks)


# SR desc words that signal a condiment/derived product rather than the food
# itself. If the query didn't ask for them, the match is off-topic.
_SR_OFFTOPIC_WORDS = frozenset(
    {"dressing", "sauce", "gravy", "dip", "spread", "soup", "juice", "syrup", "powder"}
)
# SR categories that hold composite prepared dishes — a bare ingredient query
# should never resolve to one of these.
_SR_COMPOSITE_CATEGORIES = frozenset(
    {"Restaurant Foods", "Fast Foods", "Meals, Entrees, and Side Dishes", "Baby Foods"}
)


def _sr_desc_is_offtopic(
    desc_toks: list[str], query_set: set[str], bare: bool, idx: int
) -> bool:
    """True if this SR entry is a condiment/composite that a bare ingredient
    query should not match."""
    for w in _SR_OFFTOPIC_WORDS:
        if w in desc_toks and w not in query_set:
            return True
    if bare and _SR_LEGACY is not None:
        cat = str(_SR_LEGACY[idx].get("category") or "")
        if cat in _SR_COMPOSITE_CATEGORIES:
            return True
    return False


def _search_sr_legacy(name_en: str) -> UsdaNutrition | None:
    """Token-recall search over SR Legacy (7,793 entries).

    Translates the ES name to EN via _translate() before matching.
    Requires recall >= 0.75 (≥75% of query tokens present in the SR desc).
    Takes the highest-recall match; ties broken by shorter description (more specific).
    """
    if not _SR_LEGACY or not _SR_DESC_NORM:
        return None

    query_toks = _tokens(name_en)
    if not query_toks:
        return None

    query_set = set(query_toks)
    bare = len(query_toks) <= 1  # bare single-ingredient query

    best_score = 0.74  # minimum threshold
    best_idx = -1
    for i, desc_toks in enumerate(_SR_DESC_NORM):
        # Guard: a bare ingredient query must not grab a condiment or a composite
        # prepared dish that merely mentions the ingredient (e.g. "salad" →
        # "Salad dressing, coleslaw" 404kcal; "beans" → "pupusas con frijoles").
        # The group-average fallback is closer than these mismatches.
        if _sr_desc_is_offtopic(desc_toks, query_set, bare, i):
            continue
        score = _token_recall(query_toks, desc_toks)
        if score > best_score or (score == best_score and best_idx >= 0 and len(desc_toks) < len(_SR_DESC_NORM[best_idx])):
            best_score = score
            best_idx = i

    if best_idx < 0:
        return None

    item = _SR_LEGACY[best_idx]
    kcal = float(item.get("kcal") or 0)
    if kcal <= 0:
        return None

    return UsdaNutrition(
        kcal_per_100g=kcal,
        protein_per_100g=float(item.get("protein_g") or 0),
        carbs_per_100g=float(item.get("carbs_g") or 0),
        fat_per_100g=float(item.get("fat_g") or 0),
        fiber_per_100g=float(item.get("fiber_g") or 0),
        sugar_per_100g=float(item.get("sugar_g") or 0),
        fdc_id=int(item.get("fdc_id") or 0),
        description=str(item.get("desc", ""))[:120],
    )


# ── Open Food Facts (packaged / branded products) ─────────────────────────────

async def _search_off(query: str) -> UsdaNutrition | None:
    """Open Food Facts fallback — open API, no key, strong on packaged LATAM products."""
    try:
        resp = await _get_client().get(
            _OFF_BASE,
            params={"search_terms": query, "json": 1, "page_size": 3, "action": "process"},
        )
        resp.raise_for_status()
        products = resp.json().get("products") or []
    except Exception as exc:  # noqa: BLE001  OK4: external API, fail-open
        log.debug("vision.off.request_failed", err=str(exc)[:120], query=query)
        return None

    for p in products:
        n = p.get("nutriments") or {}
        kcal = float(n.get("energy-kcal_100g") or n.get("energy_100g", 0) or 0)
        if kcal <= 0:
            continue
        protein = float(n.get("proteins_100g") or 0)
        carbs = float(n.get("carbohydrates_100g") or 0)
        fat = float(n.get("fat_100g") or 0)
        fiber = float(n.get("fiber_100g") or 0)
        sugar = float(n.get("sugars_100g") or 0)
        if protein + carbs + fat <= 0:
            continue
        return UsdaNutrition(
            kcal_per_100g=kcal,
            protein_per_100g=protein,
            carbs_per_100g=carbs,
            fat_per_100g=fat,
            fiber_per_100g=fiber,
            sugar_per_100g=sugar,
            fdc_id=0,
            description=str(p.get("product_name") or "")[:120],
        )
    return None


# ── Public API ────────────────────────────────────────────────────────────────

async def search(name: str) -> UsdaNutrition | None:
    """Search for food nutrition data, cache-first.

    Resolution: Redis cache → ES ingredient ref → SR Legacy local → Open Food Facts → None.
    Fail-open: any error returns None so the pipeline uses the group-average table.
    """
    _ensure_loaded()

    key = _cache_key(name)

    cached = await _redis_get(key)
    if cached is not None:
        log.debug("vision.usda.cache_hit", name=name[:60])
        return cached

    # 1. ES ingredient reference — direct LATAM staple lookup.
    result = _search_ingredient_ref(name)
    if result is not None:
        log.info(
            "vision.usda.ref_match",
            name=name[:60],
            kcal=result.kcal_per_100g,
            description=result.description[:60],
        )

    # 1b. Curated ES nutrition reference (recipe-engine tables) — ES-native match,
    #     no translation. Broad LATAM coverage; catches items USDA SR Legacy misses.
    if result is None:
        result = _search_nutrition_reference(name)
        if result is not None:
            log.info(
                "vision.nutrition_ref.match",
                name=name[:60],
                kcal=result.kcal_per_100g,
            )

    # 2. SR Legacy local — translate ES→EN, token-recall fuzzy.
    if result is None:
        translated = _translate(name)
        if translated:
            result = _search_sr_legacy(translated)
            if result is not None:
                log.info(
                    "vision.usda.sr_match",
                    name=name[:60],
                    translated=translated,
                    fdc_id=result.fdc_id,
                    kcal=result.kcal_per_100g,
                    description=result.description[:60],
                )

    # 3. Open Food Facts — packaged / branded products. Disabled by default
    #    (unreliable endpoint = dead latency); group-average fallback covers it.
    if result is None and _OFF_ENABLED:
        query = _translate(name) or name
        result = await _search_off(query)
        if result is not None:
            log.info(
                "vision.off.match",
                name=name[:60],
                kcal=result.kcal_per_100g,
                description=result.description[:60],
            )

    if result is not None:
        await _redis_set(key, result)

    return result
