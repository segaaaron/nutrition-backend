"""Portion size catalog: (food_type, size_category) → grams.

The LLM is poor at estimating grams from a 2D image (no depth perception,
relies on training priors). It IS good at relative visual judgments:
"is this portion XS, S, M, L, or XL compared to visible references?"

This module owns the authoritative gram values per (food type, size category).
The pipeline asks the model for a size_category; this module converts it to
grams; the existing USDA lookup then gives kcal from those grams.

Size categories (calibrated to single-person home cooking, LATAM):
    XS — very small, about 50-60% of a normal small portion
    S  — small portion
    M  — normal home serving for one adult
    L  — large serving
    XL — very large (hungry person, restaurant-size)

Gram values are derived from:
    - USDA SR Legacy typical weights
    - FAO/INFOODS LATINFOODS standard portions
    - Dietitian-reviewed LATAM cooking reference portions
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Size index
# ---------------------------------------------------------------------------

_SIZE_IDX: Final[dict[str, int]] = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}

# ---------------------------------------------------------------------------
# Portion grams per food type (XS, S, M, L, XL)
# ---------------------------------------------------------------------------

PORTION_GRAMS: Final[dict[str, tuple[int, int, int, int, int]]] = {
    # ── Poultry ─────────────────────────────────────────────────────────────
    # Breast/thigh/wing fillet. USDA: breast ~170g typical; M = home 130g.
    "poultry":          (60,  90, 130, 180, 240),
    # ── Fish fillet ─────────────────────────────────────────────────────────
    # Standard fillet 120-200g. USDA: cod fillet 180g typical.
    "fish":             (70, 100, 140, 190, 250),
    # ── Seafood (shrimp, squid, etc.) ───────────────────────────────────────
    "seafood":          (50,  80, 120, 170, 230),
    # ── Red meat (steak, chop, loin) ────────────────────────────────────────
    # USDA: beef steak 170g typical; home 120-150g.
    "red_meat":         (70, 100, 150, 200, 280),
    # ── Ground/minced meat ──────────────────────────────────────────────────
    "ground_meat":      (60,  90, 130, 180, 240),
    # ── Egg ─────────────────────────────────────────────────────────────────
    # Per-unit: large egg = 50-60g. count handles multiples.
    "egg":              (45,  50,  60,  75,  90),
    # ── Legumes (cooked) ────────────────────────────────────────────────────
    # Cooked beans/lentils. USDA: 1 cup cooked ≈ 170-180g.
    "legume":           (50,  80, 120, 180, 250),
    # ── Tofu / plant protein ────────────────────────────────────────────────
    "tofu":             (60,  90, 130, 180, 240),
    # ── Rice (cooked) ───────────────────────────────────────────────────────
    # USDA: 1 cup cooked = 186g. Home LATAM M = 150g.
    "rice":             (60, 100, 150, 220, 300),
    # ── Pasta (cooked) ──────────────────────────────────────────────────────
    # USDA: 1 cup cooked = 140g. Home plate M = 180g.
    "pasta":            (80, 120, 180, 250, 350),
    # ── Potato (boiled/mashed/baked) ────────────────────────────────────────
    "potato":           (60, 100, 150, 220, 300),
    # ── French fries ────────────────────────────────────────────────────────
    # Small side M = 130g; fast food large = 180g.
    "fries":            (70, 100, 130, 180, 250),
    # ── Bread / toast ───────────────────────────────────────────────────────
    # Per slice: standard slice = 30-35g; toast = 25-30g.
    "bread":            (20,  30,  45,  65,  90),
    # ── Corn / arepa / tortilla ─────────────────────────────────────────────
    # Corn tortilla ≈ 30g each; arepa ≈ 80-120g.
    "corn_grain":       (30,  60, 100, 150, 220),
    # ── Oats / porridge (prepared weight) ───────────────────────────────────
    # 1 cup prepared oatmeal ≈ 240g; home M = 200g.
    "oats":             (80, 130, 200, 280, 380),
    # ── Quinoa (cooked) ─────────────────────────────────────────────────────
    "quinoa":           (60, 100, 150, 220, 300),
    # ── Salad (mixed, raw) ──────────────────────────────────────────────────
    # Leafy salad is low density. M = 100g mixed.
    "salad":            (40,  70, 100, 150, 250),
    # ── Vegetables (cooked) ─────────────────────────────────────────────────
    # Side serving. M = 100g.
    "vegetable_cooked": (40,  70, 100, 150, 200),
    # ── Fruit (pieces/slices) ───────────────────────────────────────────────
    # USDA: medium apple = 182g; medium banana = 118g. M = 150g.
    "fruit":            (60, 100, 150, 220, 300),
    # ── Yogurt ──────────────────────────────────────────────────────────────
    # Standard container: 150-200g.
    "yogurt":           (80, 120, 180, 250, 350),
    # ── Milk (liquid) ───────────────────────────────────────────────────────
    "milk":            (100, 150, 250, 350, 500),
    # ── Cheese ──────────────────────────────────────────────────────────────
    # Slice/cube. Standard serving = 28-40g.
    "cheese":           (15,  25,  40,  60,  90),
    # ── Sweet / dessert ─────────────────────────────────────────────────────
    "sweet":            (40,  60, 100, 150, 220),
    # ── Smoothie / shake / juice ─────────────────────────────────────────────
    # Blended drinks: S = small glass, M = standard glass.
    "smoothie":        (150, 200, 300, 400, 550),
    # ── Soup / stew / broth ─────────────────────────────────────────────────
    # Bowl: M = 300ml; dinner plate soup = 350ml.
    "soup":            (150, 200, 300, 400, 500),
    # ── Sauce / condiment ───────────────────────────────────────────────────
    "sauce":            (10,  15,  25,  40,  60),
    # ── Oil / fat ───────────────────────────────────────────────────────────
    "fat":               (5,  10,  15,  25,  40),
    # ── Generic fallback ────────────────────────────────────────────────────
    "_default":         (50,  80, 120, 180, 250),
}

# ---------------------------------------------------------------------------
# Food type resolver (name → type key)
# ---------------------------------------------------------------------------

# Ordered list: (keyword_set, type_key). First match wins.
# Keywords are substrings checked against lowercased name.
_PATTERNS: Final[list[tuple[tuple[str, ...], str]]] = [
    # Smoothie / shake / juice — before "leche" to avoid milk match on "batido con leche"
    (("batido", "smoothie", "licuado", "shake", "jugo de", "juice", "refresco", "bebida"),  "smoothie"),
    # Soup
    (("sopa ", "soup", "caldo", "crema de", "cream of", "potaje", "chili", "estofado",
      "guiso de"),                                                                           "soup"),
    # Fat / oil — before sauce (crema agria could clash with crema de)
    (("aceite", " oil", "mantequilla", "butter", "margarina", "margarine", "manteca",
      "crema agria", "sour cream", "crème", "ghee"),                                        "fat"),
    # Fries (before potato and pasta)
    (("papas fritas", "french fries", " fries", "chips de papa", "patatas fritas"),        "fries"),
    # Potato (mashed/boiled/baked) — before generic pasta
    (("papa", "potato", "patata", "puré de"),                                              "potato"),
    # Pasta — BEFORE sauce to avoid "espagueti con salsa" matching sauce keyword
    (("pasta", "spaghetti", "espagueti", "macarrón", "macarron", "fideo", "noodle",
      "tallarín", "linguine", "penne", "fetuccini", "fetuccine", "lasaña", "lasagna",
      "ravioli"),                                                                           "pasta"),
    # Sauce / condiment — AFTER pasta
    (("salsa", "gravy", "ketchup", "soja", "vinagreta", "dressing", "mayonesa", "mayo",
      "mostaza", "salsa de", "pesto", "chimichurri", "guacamole", "hummus", "tzatziki",
      "mole", "ají", "aji ", "llajwa", "picante", "condimento"),                           "sauce"),
    # Egg — before other proteins; match "egg" at start or after space
    (("huevo", "egg ", "egg_", " egg", "tortilla de huevo", "revuelto", "estrellado",
      "pochado", "omelette", "frittata"),                                                   "egg"),
    # Poultry
    (("pollo", "chicken", "pechuga", "muslo", "thigh", "pavo", "turkey",
      "ala de", "wing"),                                                                    "poultry"),
    # Fish
    (("salmón", "salmon", "bacalao", "cod", "tilapia", "trucha", "trout",
      "pescado", " fish", "atún", "atun", "tuna", "merluza", "hake", "sardina",
      "filete de", "dorado", "surubí", "paiche", "pacu", "pejerrey"),                     "fish"),
    # Seafood
    (("camaron", "camarón", "shrimp", "prawn", "langostino", "calamar", "pulpo",
      "marisco", "seafood", "langosta", "cangrejo"),                                       "seafood"),
    # Ground meat (before red_meat)
    (("molida", "ground", "picada", "minced", "carne de burger", "carne burger",
      "hamburguesa", "burger", "albóndiga", "meatball"),                                   "ground_meat"),
    # Red meat
    (("res", " beef", "bistec", "steak", "lomo", "carne de res", "cerdo", "pork",
      "chuleta", "costilla", " rib", "cordero", "lamb", "ternera", "veal",
      "asado", "churrasco", "picanha"),                                                    "red_meat"),
    # Legumes
    (("frijol", "frijoles", " bean", "beans", "lenteja", "lentil", "garbanzo",
      "chickpea", "legumbre", "porotos", "arveja", "pea", "habichuela"),                  "legume"),
    # Tofu / plant protein
    (("tofu", "tempeh", "soya", " soy"),                                                   "tofu"),
    # Oats / cereal
    (("avena", " oat", "oats", "porridge", "granola", "cereal", "muesli", "gachas"),      "oats"),
    # Rice
    (("arroz", " rice"),                                                                   "rice"),
    # Quinoa
    (("quinoa", "quinua"),                                                                 "quinoa"),
    # Corn / arepa / tortilla
    (("arepa", "tortilla de maíz", "tortilla de maiz", "elote", "choclo",
      "chips de maíz", "nachos", "pupusa"),                                               "corn_grain"),
    # Bread
    (("pan ", "bread", "tostada", "toast", "baguette", "pita", "naan",
      "croissant", "bagel", "muffin", "pancake", "panqueque", "wafle", "waffle"),        "bread"),
    # Salad (raw leafy mix)
    (("ensalada", "salad", "lechuga", "lettuce", "rúcula", "arugula",
      "espinaca cruda", "spinach salad", "mix de hoja"),                                  "salad"),
    # Vegetables cooked
    (("brócoli", "brocoli", "broccoli", "zanahoria", "carrot", "calabacín",
      "zucchini", "espárrago", "asparagus", "coliflor", "cauliflower", "ejote",
      "green bean", "pimiento", "pepper", "verdura", "vegetable", "vegetal",
      "espinaca", "col ", "cabbage", "berenjena", "eggplant", "cebolla cocida",
      "tomate cocido", "chayote", "yuca", "mandioca", "camote", "sweet potato"),        "vegetable_cooked"),
    # Fruit
    (("fruta", "manzana", "apple", "plátano", "banana", "mango", "uva", "grape",
      "fresa", "strawberry", "naranja", "orange", "melón", "melon", "piña",
      "pineapple", "sandía", "watermelon", "pera", "pear", "durazno", "peach",
      "papaya", "kiwi", "arándano", "blueberry", "cereza", "cherry", "coco",
      "coconut", "mandarina", "tangerine", "guayaba", "guava", "maracuyá"),             "fruit"),
    # Yogurt
    (("yogur", "yogurt", "yoghurt"),                                                      "yogurt"),
    # Milk
    (("leche", " milk"),                                                                  "milk"),
    # Cheese
    (("queso", "cheese", "quesillo", "ricotta", "mozzarella", "parmesano",
      "cheddar", "brie", "cottage"),                                                      "cheese"),
    # Sweet / dessert
    (("pastel", "cake", "torta", "brownie", "helado", "ice cream", "chocolate",
      "postre", "dessert", "galleta", "cookie", "dona", "donut", "flan",
      "pudding", "turrón", "dulce", "bizcocho", "churro", "mermelada"),                 "sweet"),
]

_GROUP_FALLBACK: Final[dict[str, str]] = {
    "protein":   "_default",
    "grain":     "rice",
    "vegetable": "vegetable_cooked",
    "fruit":     "fruit",
    "dairy":     "yogurt",
    "fat":       "fat",
    "sweet":     "sweet",
    "beverage":  "smoothie",
    "other":     "_default",
}


def _resolve_food_type(name: str, food_group: str) -> str:
    n = name.lower()
    for keywords, type_key in _PATTERNS:
        if any(kw in n for kw in keywords):
            return type_key
    return _GROUP_FALLBACK.get(food_group, "_default")


def resolve_grams(name: str, food_group: str, size_category: str) -> int:
    """Return evidence-based grams for (name, size_category).

    Returns 0 if size_category is unrecognized → caller falls back to LLM grams.
    """
    idx = _SIZE_IDX.get(size_category.upper().strip())
    if idx is None:
        return 0
    food_type = _resolve_food_type(name, food_group)
    return PORTION_GRAMS.get(food_type, PORTION_GRAMS["_default"])[idx]
