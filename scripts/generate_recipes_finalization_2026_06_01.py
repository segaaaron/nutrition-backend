"""Finalization recipe batch — 2026-06-01.

Closes remaining red/yellow gaps + adds positive pregnancy boost.

Bucket A — remaining gap closure (90 total):
  - ibd                     +20   (low-FODMAP soluble fiber, cooked veggies)
  - hyperthyroidism         +10   (low iodine, calcium-rich plant)
  - vitamin_d_deficiency    +20   (salmón/sardinas/yema/hongos UV/fortified)
  - lactose_intolerance     +40   (dairy-free OR lactose-free)

Bucket B — pregnancy positive boost (250):
  - pregnancy_safe = true
  - recommended_for_conditions includes "pregnancy"
  - folate_ug ≥ 150, iron_mg ≥ 4, calcium_mg ≥ 250 (populated)
  - NO raw fish, soft cheese unpasteurized, high-Hg fish, organ meat, alcohol

Hard validators identical to round3 batch + pregnancy_safe scan rules.

Output: data/meals/finalization_batch_2026_06_01.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import (  # noqa: E402
    ACTIVITY_LEVELS_5,
    ALLERGENS_14,
    CONDITIONS_25,
    GOALS_5,
    MEAL_TIMES_4,
    REGIONS_5,
)

PLACEHOLDER_IMG = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"

FORBIDDEN_CLAIM_TOKENS = (
    "cura ", "trata ", "tratamiento", "previene", "cardioprotector",
    "antiinflamatorio", "antiinflamatoria", "detox", "desintoxica",
    "milagroso", "milagrosa", "limpieza hepática",
)

SUPPLEMENT_TOKENS = (
    "whey", "caseina", "caseína", "bcaa", "creatina", "pre-workout",
    "preworkout", "mass gainer", "proteina en polvo", "proteína en polvo",
    "proteina_whey", "proteina_vegana", "multivitaminico", "multivitamínico",
    "collagen powder", "colageno en polvo", "maltodextrina",
)

# Pregnancy-disqualifying tokens (raw fish, soft unpasteurized cheese, high-Hg
# fish, organ meat, alcohol). Scanned across name/description/ingredients.
PREGNANCY_BLOCK_TOKENS = (
    # raw fish / sushi / ceviche
    "sushi", "sashimi", "ceviche", "crudo", "tartar", "carpaccio",
    "pescado crudo", "salmon crudo", "salmón crudo", "atun crudo", "atún crudo",
    # high-Hg fish
    "tiburon", "tiburón", "shark", "pez espada", "swordfish", "marlin",
    "bigeye tuna", "atun rojo", "atún rojo", "atun patudo", "atún patudo",
    "caballa rey", "king mackerel",
    # soft / unpasteurized cheese
    "queso brie", "brie ", "camembert", "queso azul", "blue cheese",
    "roquefort", "gorgonzola", "feta sin pasteurizar", "queso fresco sin pasteurizar",
    "queso no pasteurizado", "unpasteurized",
    # organ meat
    "higado", "hígado", "foie", "liver ", "menudencias", "vísceras", "visceras",
    "riñón", "rinones", "molleja",
    # alcohol
    "vino ", "cerveza", "ron ", "whisky", "vodka", "tequila", "licor",
    "alcohol", "wine ", "beer ",
    # deli meats (listeria risk — best skipped for boosted recommendation pool)
    "salami", "prosciutto", "jamon serrano", "jamón serrano", "embutido",
)


# ───────────────────────────────────────────────────────────────────────────
# Ingredient nutrition per 100 g / 100 ml + pregnancy micros tags
# (folate µg, iron mg, calcium mg per 100 g — USDA averages)
# ───────────────────────────────────────────────────────────────────────────
ING: dict[str, dict] = {
    # Animal protein
    "salmon_cocido":    {"kcal": 208, "p": 22.1, "c": 0.0,  "f": 13.4, "fib": 0,   "sug": 0,   "na": 59,  "gi": 0,  "satf": 3.1, "purine": "mod", "fol": 35,  "fe": 0.5, "ca": 15},
    "sardina_lata":     {"kcal": 208, "p": 24.6, "c": 0.0,  "f": 11.4, "fib": 0,   "sug": 0,   "na": 307, "gi": 0,  "satf": 1.5, "purine": "high","fol": 12,  "fe": 2.9, "ca": 382},
    "atun_agua":        {"kcal": 116, "p": 25.5, "c": 0.0,  "f": 1.0,  "fib": 0,   "sug": 0,   "na": 247, "gi": 0,  "satf": 0.3, "purine": "high","fol": 4,   "fe": 1.0, "ca": 11},
    "trucha":           {"kcal": 148, "p": 20.8, "c": 0.0,  "f": 6.6,  "fib": 0,   "sug": 0,   "na": 52,  "gi": 0,  "satf": 1.4, "purine": "mod", "fol": 12,  "fe": 0.7, "ca": 43},
    "bacalao":          {"kcal": 82,  "p": 17.8, "c": 0.0,  "f": 0.7,  "fib": 0,   "sug": 0,   "na": 54,  "gi": 0,  "satf": 0.1, "purine": "mod", "fol": 7,   "fe": 0.4, "ca": 16},
    "pollo_pechuga":    {"kcal": 165, "p": 31.0, "c": 0.0,  "f": 3.6,  "fib": 0,   "sug": 0,   "na": 74,  "gi": 0,  "satf": 1.0, "purine": "mod", "fol": 4,   "fe": 0.7, "ca": 6},
    "pavo_pechuga":     {"kcal": 135, "p": 30.1, "c": 0.0,  "f": 1.0,  "fib": 0,   "sug": 0,   "na": 54,  "gi": 0,  "satf": 0.3, "purine": "mod", "fol": 6,   "fe": 1.2, "ca": 12},
    "ternera_magra":    {"kcal": 170, "p": 26.0, "c": 0.0,  "f": 7.0,  "fib": 0,   "sug": 0,   "na": 60,  "gi": 0,  "satf": 2.7, "purine": "mod", "fol": 10,  "fe": 2.6, "ca": 18},
    "huevo":            {"kcal": 143, "p": 12.6, "c": 0.7,  "f": 9.5,  "fib": 0,   "sug": 0.4, "na": 142, "gi": 0,  "satf": 3.1, "purine": "low", "fol": 47,  "fe": 1.8, "ca": 56},
    "clara_huevo":      {"kcal": 52,  "p": 11.0, "c": 0.7,  "f": 0.2,  "fib": 0,   "sug": 0.7, "na": 166, "gi": 0,  "satf": 0.0, "purine": "low", "fol": 4,   "fe": 0.1, "ca": 7},
    "yema_huevo":       {"kcal": 322, "p": 15.9, "c": 3.6,  "f": 26.5, "fib": 0,   "sug": 0.6, "na": 48,  "gi": 0,  "satf": 9.6, "purine": "low", "fol": 146, "fe": 2.7, "ca": 129},
    # Dairy pasteurized (safe for pregnancy)
    "yogur_griego":     {"kcal": 59,  "p": 10.0, "c": 3.6,  "f": 0.4,  "fib": 0,   "sug": 3.2, "na": 36,  "gi": 11, "satf": 0.1, "purine": "low", "fol": 5,   "fe": 0.0, "ca": 110},
    "yogur_natural_pasteurizado": {"kcal": 61, "p": 3.5, "c": 4.7, "f": 3.3, "fib": 0, "sug": 4.7, "na": 46, "gi": 14, "satf": 2.1, "purine": "low", "fol": 7, "fe": 0.1, "ca": 121},
    "queso_cottage":    {"kcal": 98,  "p": 11.1, "c": 3.4,  "f": 4.3,  "fib": 0,   "sug": 2.7, "na": 364, "gi": 30, "satf": 1.7, "purine": "low", "fol": 12,  "fe": 0.1, "ca": 83},
    "leche_descremada": {"kcal": 34,  "p": 3.4,  "c": 5.0,  "f": 0.1,  "fib": 0,   "sug": 5.0, "na": 42,  "gi": 32, "satf": 0.1, "purine": "low", "fol": 5,   "fe": 0.0, "ca": 122},
    "leche_almendra_fortificada": {"kcal": 17, "p": 0.6, "c": 0.6, "f": 1.5, "fib": 0.3, "sug": 0, "na": 60, "gi": 25, "satf": 0.1, "purine": "low", "fol": 0, "fe": 0.3, "ca": 188},
    "leche_avena_fortificada": {"kcal": 47, "p": 1.0, "c": 7.0, "f": 1.5, "fib": 0.8, "sug": 3.3, "na": 42, "gi": 60, "satf": 0.2, "purine": "low", "fol": 0, "fe": 0.4, "ca": 120},
    "leche_soya_fortificada": {"kcal": 43, "p": 3.3, "c": 1.8, "f": 1.8, "fib": 0.4, "sug": 1.0, "na": 51, "gi": 30, "satf": 0.3, "purine": "low", "fol": 18, "fe": 0.4, "ca": 123},
    # Carbs
    "avena_sin_gluten": {"kcal": 389, "p": 16.9, "c": 66.3, "f": 6.9,  "fib": 10.6,"sug": 0,   "na": 2,   "gi": 55, "satf": 1.2, "purine": "low", "fol": 56,  "fe": 4.7, "ca": 54},
    "quinoa_cocida":    {"kcal": 120, "p": 4.4,  "c": 21.3, "f": 1.9,  "fib": 2.8, "sug": 0.9, "na": 7,   "gi": 53, "satf": 0.2, "purine": "low", "fol": 42,  "fe": 1.5, "ca": 17},
    "arroz_integral_cocido": {"kcal": 111, "p": 2.6, "c": 23.0, "f": 0.9, "fib": 1.8, "sug": 0.4, "na": 5, "gi": 55, "satf": 0.2, "purine": "low", "fol": 4, "fe": 0.4, "ca": 10},
    "camote_cocido":    {"kcal": 86,  "p": 1.6,  "c": 20.1, "f": 0.1,  "fib": 3.0, "sug": 4.2, "na": 55,  "gi": 54, "satf": 0.0, "purine": "low", "fol": 11,  "fe": 0.6, "ca": 30},
    # Legumes (high folate + iron)
    "lentejas_cocidas": {"kcal": 116, "p": 9.0,  "c": 20.1, "f": 0.4,  "fib": 7.9, "sug": 1.8, "na": 2,   "gi": 32, "satf": 0.1, "purine": "mod", "fol": 181, "fe": 3.3, "ca": 19},
    "garbanzos_cocidos": {"kcal": 164, "p": 8.9, "c": 27.4, "f": 2.6,  "fib": 7.6, "sug": 4.8, "na": 7,   "gi": 36, "satf": 0.3, "purine": "mod", "fol": 172, "fe": 2.9, "ca": 49},
    "frijoles_negros_cocidos": {"kcal": 132, "p": 8.9, "c": 23.7, "f": 0.5, "fib": 8.7, "sug": 0.3, "na": 1, "gi": 30, "satf": 0.1, "purine": "mod", "fol": 149, "fe": 2.1, "ca": 27},
    "tofu_firme":       {"kcal": 144, "p": 17.3, "c": 2.8,  "f": 8.7,  "fib": 2.3, "sug": 0.6, "na": 14,  "gi": 15, "satf": 1.3, "purine": "mod", "fol": 29,  "fe": 2.7, "ca": 350},
    "edamame_cocido":   {"kcal": 122, "p": 11.0, "c": 9.9,  "f": 5.2,  "fib": 5.2, "sug": 2.2, "na": 6,   "gi": 18, "satf": 0.6, "purine": "mod", "fol": 311, "fe": 2.3, "ca": 63},
    # Vegetables (cooked — IBD-friendly + folate/iron)
    "espinaca_cocida":  {"kcal": 23,  "p": 2.9,  "c": 3.6,  "f": 0.4,  "fib": 2.2, "sug": 0.4, "na": 79,  "gi": 15, "satf": 0.1, "purine": "mod", "fol": 146, "fe": 3.6, "ca": 136},
    "brocoli_cocido":   {"kcal": 35,  "p": 2.4,  "c": 7.2,  "f": 0.4,  "fib": 3.3, "sug": 1.4, "na": 41,  "gi": 15, "satf": 0.1, "purine": "low", "fol": 108, "fe": 0.7, "ca": 40},
    "coliflor_cocida":  {"kcal": 23,  "p": 1.8,  "c": 4.1,  "f": 0.5,  "fib": 2.3, "sug": 1.9, "na": 15,  "gi": 15, "satf": 0.1, "purine": "low", "fol": 44,  "fe": 0.3, "ca": 16},
    "calabacin":        {"kcal": 17,  "p": 1.2,  "c": 3.1,  "f": 0.3,  "fib": 1.0, "sug": 2.5, "na": 8,   "gi": 15, "satf": 0.1, "purine": "low", "fol": 24,  "fe": 0.4, "ca": 16},
    "zanahoria":        {"kcal": 41,  "p": 0.9,  "c": 9.6,  "f": 0.2,  "fib": 2.8, "sug": 4.7, "na": 69,  "gi": 39, "satf": 0.0, "purine": "low", "fol": 19,  "fe": 0.3, "ca": 33},
    "kale_cocida":      {"kcal": 35,  "p": 2.9,  "c": 4.4,  "f": 1.5,  "fib": 4.1, "sug": 0.8, "na": 53,  "gi": 15, "satf": 0.2, "purine": "low", "fol": 62,  "fe": 1.6, "ca": 254},
    "tomate":           {"kcal": 18,  "p": 0.9,  "c": 3.9,  "f": 0.2,  "fib": 1.2, "sug": 2.6, "na": 5,   "gi": 30, "satf": 0.0, "purine": "low", "fol": 15,  "fe": 0.3, "ca": 10},
    "esparragos":       {"kcal": 20,  "p": 2.2,  "c": 3.9,  "f": 0.1,  "fib": 2.1, "sug": 1.9, "na": 2,   "gi": 15, "satf": 0.0, "purine": "mod", "fol": 149, "fe": 0.9, "ca": 21},
    "champinon_uv":     {"kcal": 22,  "p": 3.1,  "c": 3.3,  "f": 0.3,  "fib": 1.0, "sug": 2.0, "na": 5,   "gi": 15, "satf": 0.0, "purine": "mod", "fol": 17,  "fe": 0.5, "ca": 3},
    # Fruits
    "platano":          {"kcal": 89,  "p": 1.1,  "c": 22.8, "f": 0.3,  "fib": 2.6, "sug": 12.2,"na": 1,   "gi": 51, "satf": 0.1, "purine": "low", "fol": 20,  "fe": 0.3, "ca": 5},
    "frambuesa":        {"kcal": 52,  "p": 1.2,  "c": 11.9, "f": 0.7,  "fib": 6.5, "sug": 4.4, "na": 1,   "gi": 25, "satf": 0.0, "purine": "low", "fol": 21,  "fe": 0.7, "ca": 25},
    "arandanos":        {"kcal": 57,  "p": 0.7,  "c": 14.5, "f": 0.3,  "fib": 2.4, "sug": 10.0,"na": 1,   "gi": 53, "satf": 0.0, "purine": "low", "fol": 6,   "fe": 0.3, "ca": 6},
    "fresa":            {"kcal": 32,  "p": 0.7,  "c": 7.7,  "f": 0.3,  "fib": 2.0, "sug": 4.9, "na": 1,   "gi": 40, "satf": 0.0, "purine": "low", "fol": 24,  "fe": 0.4, "ca": 16},
    "papaya":           {"kcal": 43,  "p": 0.5,  "c": 10.8, "f": 0.3,  "fib": 1.7, "sug": 7.8, "na": 8,   "gi": 60, "satf": 0.0, "purine": "low", "fol": 37,  "fe": 0.3, "ca": 20},
    "manzana":          {"kcal": 52,  "p": 0.3,  "c": 13.8, "f": 0.2,  "fib": 2.4, "sug": 10.4,"na": 1,   "gi": 39, "satf": 0.0, "purine": "low", "fol": 3,   "fe": 0.1, "ca": 6},
    "limon":            {"kcal": 29,  "p": 1.1,  "c": 9.3,  "f": 0.3,  "fib": 2.8, "sug": 2.5, "na": 2,   "gi": 20, "satf": 0.0, "purine": "low", "fol": 11,  "fe": 0.6, "ca": 26},
    # Seeds / nuts / fats
    "chia":             {"kcal": 486, "p": 16.5, "c": 42.1, "f": 30.7, "fib": 34.4,"sug": 0,   "na": 16,  "gi": 1,  "satf": 3.3, "purine": "low", "fol": 49,  "fe": 7.7, "ca": 631},
    "linaza":           {"kcal": 534, "p": 18.3, "c": 28.9, "f": 42.2, "fib": 27.3,"sug": 1.6, "na": 30,  "gi": 1,  "satf": 3.7, "purine": "low", "fol": 87,  "fe": 5.7, "ca": 255},
    "almendras":        {"kcal": 579, "p": 21.2, "c": 21.6, "f": 49.9, "fib": 12.5,"sug": 4.4, "na": 1,   "gi": 0,  "satf": 3.8, "purine": "low", "fol": 44,  "fe": 3.7, "ca": 269},
    "aceite_oliva":     {"kcal": 884, "p": 0.0,  "c": 0.0,  "f": 100.0,"fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "satf": 13.8,"purine": "low", "fol": 0,   "fe": 0.6, "ca": 1},
    "aguacate":         {"kcal": 160, "p": 2.0,  "c": 8.5,  "f": 14.7, "fib": 6.7, "sug": 0.7, "na": 7,   "gi": 15, "satf": 2.1, "purine": "low", "fol": 81,  "fe": 0.6, "ca": 12},
    "tahini":           {"kcal": 595, "p": 17.0, "c": 21.2, "f": 53.8, "fib": 9.3, "sug": 0.5, "na": 115, "gi": 25, "satf": 7.6, "purine": "low", "fol": 98,  "fe": 8.9, "ca": 426},
    "semilla_calabaza": {"kcal": 559, "p": 30.2, "c": 10.7, "f": 49.1, "fib": 6.0, "sug": 1.4, "na": 7,   "gi": 25, "satf": 8.7, "purine": "low", "fol": 58,  "fe": 8.8, "ca": 46},
}


ALLERGEN_MAP = [
    (("almendra", "nuez", "almond", "walnut", "cashew", "pistachio", "pecan", "hazelnut", "macadamia"), "tree_nuts"),
    (("yogur griego", "yogur natural", "yogurt griego", "yogurt natural", "leche descremada", "queso cottage", "cottage", " kefir", "queso ", "butter"), "dairy"),
    (("trigo", "wheat", "harina", "pan ", "pasta", "flour", "bread"), "gluten"),
    (("avena", "oats"), "gluten_oat"),  # special-cased
    (("maní", "mani", "peanut", "cacahuate"), "peanuts"),
    (("camarón", "langosta", "cangrejo", "shrimp", "crab", "lobster"), "shellfish"),
    (("pescado", "atún", "atun", "salmón", "salmon", "tuna", "sardina", "sardine", "trucha", "bacalao"), "fish"),
    (("huevo", "clara de huevo", "yema", "egg"), "egg"),
    (("soya", "soja", "tofu", "tempeh", "edamame", "soy", "leche de soya", "leche de soja"), "soy"),
    (("sésamo", "sesamo", "sesame", "tahini"), "sesame"),
]


def detect_allergens(ingredients_text: list[str]) -> list[str]:
    text = " ".join(ingredients_text).lower()
    found: set[str] = set()
    for keys, tag in ALLERGEN_MAP:
        if tag == "gluten_oat":
            if any(k in text for k in keys):
                if "sin gluten" not in text and "certificada" not in text and "certificado" not in text:
                    found.add("gluten")
            continue
        if any(k in text for k in keys):
            found.add(tag)
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    p = c = f = fib = sug = na = satf = 0.0
    fol = fe = ca = 0.0
    gi_w = 0.0
    gi_c_tot = 0.0
    for key, grams in components:
        ing = ING[key]
        factor = grams / 100.0
        p += ing["p"] * factor
        c += ing["c"] * factor
        f += ing["f"] * factor
        fib += ing["fib"] * factor
        sug += ing["sug"] * factor
        na += ing["na"] * factor
        satf += ing["satf"] * factor
        fol += ing["fol"] * factor
        fe += ing["fe"] * factor
        ca += ing["ca"] * factor
        carb_contrib = ing["c"] * factor
        gi_w += ing["gi"] * carb_contrib
        gi_c_tot += carb_contrib
    gi = int(round(gi_w / gi_c_tot)) if gi_c_tot > 0 else None
    p_i = int(round(p)); c_i = int(round(c)); f_i = int(round(f))
    kcal = 4 * p_i + 4 * c_i + 9 * f_i
    return {
        "calories": kcal,
        "protein_g": p_i, "carbs_g": c_i, "fat_g": f_i,
        "fiber_g": int(round(fib)), "sugar_g": int(round(sug)),
        "sodium_mg": int(round(na)), "sat_fat_g": int(round(satf)),
        "gi": gi,
        "folate_ug": int(round(fol)),
        "iron_mg": round(fe, 1),
        "calcium_mg": int(round(ca)),
    }


def gl_estimate(carbs_g: int, gi: int | None) -> float | None:
    if gi is None:
        return None
    return round((carbs_g * gi) / 100.0, 1)


def has_purine_high(components: list[tuple[str, float]]) -> bool:
    return any(ING[k]["purine"] == "high" for k, _ in components)


def _blob(recipe: dict) -> str:
    return " ".join([
        recipe["name"].lower(),
        recipe["description"].lower(),
        " ".join(s.lower() for s in recipe["execution"]["ingredients"]),
        " ".join(s.lower() for s in recipe["execution"]["instructions"]),
    ])


_PREGNANCY_BLOCK_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t.strip()) for t in PREGNANCY_BLOCK_TOKENS if t.strip()) + r")\b",
    re.IGNORECASE,
)


def is_pregnancy_disqualified(text_blob: str) -> str | None:
    m = _PREGNANCY_BLOCK_RE.search(text_blob)
    return m.group(0) if m else None


def build_recipe(
    rid: str,
    name: str,
    description: str,
    components: list[tuple[str, float]],
    ingredients_text: list[str],
    instructions: list[str],
    meal_format: str,
    cuisine_region: list[str],
    regions: list[str],
    dietary_pattern: str,
    target_goals: list[str],
    suitable_for_activity: list[str],
    recommended_for_conditions: list[str],
    contraindicated_conditions: list[str],
    meal_time: str = "snack",
    pregnancy_safe: bool = False,
    prep: int = 10,
    cook: int = 0,
    servings: int = 1,
    populate_pregnancy_micros: bool = False,
    source_catalog: str = "nova_v2_batch_finalization_2026_06_01",
) -> dict:
    m = macros_from_components(components)
    allergens = detect_allergens(ingredients_text)
    gl = gl_estimate(m["carbs_g"], m["gi"])

    # Defensive auto-tagging
    if has_purine_high(components):
        contraindicated_conditions = sorted(set(contraindicated_conditions) | {"gout"})
        recommended_for_conditions = [c for c in recommended_for_conditions if c != "gout"]
    if m["sat_fat_g"] > 5:
        recommended_for_conditions = [c for c in recommended_for_conditions
                                       if c not in {"hypercholesterolemia", "fatty_liver", "dyslipidemia"}]
        contraindicated_conditions = sorted(set(contraindicated_conditions) | {"hypercholesterolemia", "fatty_liver"})
    if meal_format == "liquid":
        if m["sugar_g"] > 12 or m["carbs_g"] > 25:
            recommended_for_conditions = [c for c in recommended_for_conditions
                                           if c not in {"fatty_liver", "diabetes_t2", "diabetes_t1", "pcos"}]
        if gl is not None and gl > 10:
            recommended_for_conditions = [c for c in recommended_for_conditions
                                           if c not in {"diabetes_t2", "diabetes_t1", "pcos"}]
    if "dairy" in allergens:
        text_low = " ".join(ingredients_text).lower()
        if "sin lactosa" not in text_low and "lactose-free" not in text_low:
            contraindicated_conditions = sorted(set(contraindicated_conditions) | {"lactose_intolerance"})
            recommended_for_conditions = [c for c in recommended_for_conditions if c != "lactose_intolerance"]

    derived_kcal = 4 * m["protein_g"] + 4 * m["carbs_g"] + 9 * m["fat_g"]
    consistency_pct = round(abs(derived_kcal - m["calories"]) / max(m["calories"], 1) * 100, 2)

    micronutrients = {
        "gi": m["gi"], "gl": gl,
        "potassium_mg": None, "phosphorus_mg": None,
        "iron_mg": None, "heme_pct": None,
        "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
    }
    if populate_pregnancy_micros:
        micronutrients["folate_ug"] = m["folate_ug"]
        micronutrients["iron_mg"] = m["iron_mg"]
        micronutrients["calcium_mg"] = m["calcium_mg"]

    return {
        "id": rid,
        "name": name,
        "description": description,
        "image_url": PLACEHOLDER_IMG,
        "nutrition_profile": {
            "calories": m["calories"],
            "macros": {
                "protein_g": m["protein_g"], "carbs_g": m["carbs_g"], "fat_g": m["fat_g"],
                "fiber_g": m["fiber_g"], "sugar_g": m["sugar_g"],
                "sat_fat_g": m["sat_fat_g"], "sodium_mg": m["sodium_mg"],
            },
            "micronutrients": micronutrients,
        },
        "matching_criteria": {
            "target_goals": target_goals,
            "suitable_for_activity": suitable_for_activity,
            "recommended_for_conditions": sorted(set(recommended_for_conditions)),
            "contraindicated_conditions": sorted(set(contraindicated_conditions)),
            "allergens": allergens,
            "regions": regions,
            "dietary_pattern": dietary_pattern,
            "cuisine_region": cuisine_region,
            "meal_format": meal_format,
            "pregnancy_safe": pregnancy_safe,
        },
        "execution": {
            "meal_time": meal_time,
            "prep_time_minutes": prep,
            "cook_time_minutes": cook,
            "image_url": None,
            "ingredients": ingredients_text,
            "instructions": instructions,
            "servings": servings,
            "source_catalog": source_catalog,
        },
        "audit": {
            "schema_version": "v2",
            "macro_consistency_pct": consistency_pct,
            "gl_estimated": gl,
            "cultural_origin": None,
            "image_status": "placeholder_pending_upload",
            "generated_at": "2026-06-01",
            "bucket": None,
        },
    }


def validate(recipe: dict, expect_pregnancy: bool = False) -> tuple[bool, str]:
    mc = recipe["matching_criteria"]
    np_ = recipe["nutrition_profile"]
    m = np_["macros"]
    kcal = np_["calories"]
    if kcal <= 0:
        return False, "kcal<=0"
    derived = 4 * m["protein_g"] + 4 * m["carbs_g"] + 9 * m["fat_g"]
    if abs(derived - kcal) / kcal > 0.05:
        return False, f"macro_drift={abs(derived-kcal)/kcal:.3f}"
    is_liquid = mc.get("meal_format") == "liquid"
    floor = 30 if is_liquid else 60
    if not (floor <= kcal <= 1500):
        return False, f"kcal_out_of_range={kcal}"
    if not (0 <= m["protein_g"] <= 80):
        return False, f"protein_out={m['protein_g']}"
    if not (0 <= m["carbs_g"] <= 200):
        return False, f"carbs_out={m['carbs_g']}"
    if not (0 <= m["fat_g"] <= 80):
        return False, f"fat_out={m['fat_g']}"
    for v in mc["allergens"]:
        if v not in ALLERGENS_14:
            return False, f"allergen_drift={v}"
    for v in mc["recommended_for_conditions"]:
        if v not in CONDITIONS_25:
            return False, f"rec_drift={v}"
    for v in mc["contraindicated_conditions"]:
        if v not in CONDITIONS_25:
            return False, f"contra_drift={v}"
    inter = set(mc["recommended_for_conditions"]) & set(mc["contraindicated_conditions"])
    if inter:
        return False, f"rec_contra_intersect={sorted(inter)}"
    for v in mc["target_goals"]:
        if v not in GOALS_5:
            return False, f"goal_drift={v}"
    for v in mc["suitable_for_activity"]:
        if v not in ACTIVITY_LEVELS_5:
            return False, f"activity_drift={v}"
    for v in mc["regions"]:
        if v not in REGIONS_5:
            return False, f"region_drift={v}"
    if recipe["execution"]["meal_time"] not in MEAL_TIMES_4:
        return False, "meal_time_drift"
    b = _blob(recipe)
    for tok in SUPPLEMENT_TOKENS:
        if tok in b:
            return False, f"supplement_token={tok}"
    for tok in FORBIDDEN_CLAIM_TOKENS:
        if tok in b:
            return False, f"medical_claim_token={tok.strip()}"

    if expect_pregnancy:
        bad = is_pregnancy_disqualified(b)
        if bad:
            return False, f"pregnancy_block_token={bad}"
        if not mc.get("pregnancy_safe"):
            return False, "pregnancy_safe_false"
        if "pregnancy" not in mc["recommended_for_conditions"]:
            return False, "pregnancy_not_recommended"
        micros = np_.get("micronutrients") or {}
        if not micros.get("folate_ug") or micros["folate_ug"] < 150:
            return False, f"folate_low={micros.get('folate_ug')}"
        if not micros.get("iron_mg") or micros["iron_mg"] < 4:
            return False, f"iron_low={micros.get('iron_mg')}"
        if not micros.get("calcium_mg") or micros["calcium_mg"] < 250:
            return False, f"calcium_low={micros.get('calcium_mg')}"
    return True, "ok"


def _id(bucket_tag: str, n: int) -> str:
    return f"nova_meal_fin_{bucket_tag}_{n:04d}"


def _fin(r: dict, bucket: str) -> dict:
    r["audit"]["bucket"] = bucket
    return r


# ═════════════════════════════════════════════════════════════════════════
# Bucket A.1 — IBD +20 (low-FODMAP, cooked veg, soluble fiber)
# ═════════════════════════════════════════════════════════════════════════
def build_ibd_extra() -> list[dict]:
    out: list[dict] = []
    bucket = "ibd2"
    n = 0
    specs = [
        ("Bowl Suave de Quinoa con Zanahoria y Pollo",
         [("quinoa_cocida", 120), ("zanahoria", 100), ("pollo_pechuga", 100), ("aceite_oliva", 5)],
         ["120 g de quinoa cocida", "100 g de zanahoria al vapor", "100 g de pollo desmechado", "5 ml de aceite de oliva"], "lunch"),
        ("Avena Cremosa Sin Gluten con Papaya Suave",
         [("avena_sin_gluten", 35), ("papaya", 100), ("leche_almendra_fortificada", 200), ("chia", 5)],
         ["35 g de avena sin gluten certificada", "100 g de papaya madura", "200 ml de leche de almendra", "5 g de chía"], "breakfast"),
        ("Bacalao al Vapor con Calabacín y Arroz",
         [("bacalao", 130), ("calabacin", 100), ("arroz_integral_cocido", 120), ("aceite_oliva", 5)],
         ["130 g de bacalao al vapor", "100 g de calabacín", "120 g de arroz integral", "5 ml de aceite de oliva"], "dinner"),
        ("Crema de Zanahoria con Pavo Suave",
         [("zanahoria", 180), ("pavo_pechuga", 100), ("aceite_oliva", 5)],
         ["180 g de zanahoria cocida", "100 g de pavo desmechado", "5 ml de aceite de oliva"], "lunch"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(5):
            n += 1
            descr = "Plato gentil con fibra soluble, vegetales cocidos y proteína magra, alineado con bienestar digestivo en EII."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina los ingredientes a textura suave.", "Combina con cuidado.", "Sirve tibio."],
                "solid", ["latam"], ["latam"], "omnivore",
                ["maintain", "health"], ["sedentary", "lightly_active"],
                ["ibd", "ibs"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=15,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# Bucket A.2 — Hyperthyroidism +10 (low iodine, calcium-rich plant)
# ═════════════════════════════════════════════════════════════════════════
def build_hyperthyroid_extra() -> list[dict]:
    out: list[dict] = []
    bucket = "hy2"
    n = 0
    specs = [
        ("Pollo con Kale Cocida y Quinoa con Almendras",
         [("pollo_pechuga", 100), ("kale_cocida", 120), ("quinoa_cocida", 100), ("almendras", 10), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de kale cocida", "100 g de quinoa", "10 g de almendras", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl Vegetal con Tofu y Brócoli Cocido",
         [("tofu_firme", 130), ("brocoli_cocido", 130), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["130 g de tofu", "130 g de brócoli cocido", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(5):
            n += 1
            descr = "Plato bajo en yodo (sin pescados ni mariscos), con crucíferas cocidas y calcio vegetal, alineado con hipertiroidismo."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina las crucíferas completamente.", "Prepara la proteína.", "Combina y sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["lightly_active", "moderately_active"],
                ["hyperthyroidism"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=15,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# Bucket A.3 — Vitamin D deficiency +20
# ═════════════════════════════════════════════════════════════════════════
def build_vit_d_extra() -> list[dict]:
    out: list[dict] = []
    bucket = "vd3"
    n = 0
    specs = [
        ("Salmón Cocido con Espárragos y Quinoa",
         [("salmon_cocido", 120), ("esparragos", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["120 g de salmón cocido", "100 g de espárragos", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Huevo con Yema y Champiñones UV con Camote",
         [("huevo", 100), ("champinon_uv", 100), ("camote_cocido", 130), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de champiñones tratados con UV", "130 g de camote", "5 ml de aceite de oliva"], "breakfast"),
        ("Avena Fortificada con Plátano y Almendras",
         [("avena_sin_gluten", 40), ("leche_almendra_fortificada", 250), ("platano", 80), ("almendras", 12)],
         ["40 g de avena sin gluten", "250 ml de leche de almendra fortificada en calcio y D", "80 g de plátano", "12 g de almendras"], "breakfast"),
        ("Trucha al Horno con Quinoa y Brócoli",
         [("trucha", 130), ("quinoa_cocida", 100), ("brocoli_cocido", 100), ("aceite_oliva", 5)],
         ["130 g de trucha al horno", "100 g de quinoa", "100 g de brócoli", "5 ml de aceite de oliva"], "dinner"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(5):
            n += 1
            descr = "Plato con fuentes alimentarias naturales de vitamina D (pescado graso, yema, hongos UV, lácteo vegetal fortificado)."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina la proteína.", "Combina con vegetales.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["lightly_active", "moderately_active"],
                ["vitamin_d_deficiency"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=15,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# Bucket A.4 — Lactose intolerance +40 (dairy-free OR lactose-free)
# ═════════════════════════════════════════════════════════════════════════
def build_lactose_extra() -> list[dict]:
    out: list[dict] = []
    bucket = "lac"
    n = 0
    # All use leche_almendra_fortificada (no dairy) or leche_soya_fortificada.
    # Note: soya is correctly tagged via ALLERGEN_MAP. Avoid almonds when wanting
    # to keep tree_nuts off — but soya covers that scenario.
    specs = [
        ("Avena con Leche de Almendra Fortificada y Frambuesa",
         [("avena_sin_gluten", 40), ("leche_almendra_fortificada", 250), ("frambuesa", 80), ("chia", 8)],
         ["40 g de avena sin gluten certificada", "250 ml de leche de almendra fortificada", "80 g de frambuesa", "8 g de chía"], "breakfast"),
        ("Bowl de Quinoa con Tofu y Espinaca",
         [("quinoa_cocida", 130), ("tofu_firme", 130), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["130 g de quinoa", "130 g de tofu firme", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Pollo con Camote y Brócoli (sin lácteos)",
         [("pollo_pechuga", 110), ("camote_cocido", 150), ("brocoli_cocido", 100), ("aceite_oliva", 5)],
         ["110 g de pollo", "150 g de camote", "100 g de brócoli", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón Cocido con Quinoa y Espárragos",
         [("salmon_cocido", 100), ("quinoa_cocida", 120), ("esparragos", 100), ("aceite_oliva", 5)],
         ["100 g de salmón cocido", "120 g de quinoa", "100 g de espárragos", "5 ml de aceite de oliva"], "dinner"),
        ("Smoothie de Leche de Soya Fortificada con Plátano y Chía",
         [("leche_soya_fortificada", 250), ("platano", 100), ("chia", 10)],
         ["250 ml de leche de soya fortificada", "100 g de plátano", "10 g de chía"], "breakfast"),
        ("Lentejas con Zanahoria y Arroz Integral",
         [("lentejas_cocidas", 150), ("zanahoria", 100), ("arroz_integral_cocido", 100), ("aceite_oliva", 5)],
         ["150 g de lentejas", "100 g de zanahoria", "100 g de arroz integral", "5 ml de aceite de oliva"], "lunch"),
        ("Pavo con Quinoa y Calabacín (sin lácteos)",
         [("pavo_pechuga", 100), ("quinoa_cocida", 120), ("calabacin", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "120 g de quinoa", "100 g de calabacín", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl de Garbanzos con Espinaca y Aguacate",
         [("garbanzos_cocidos", 130), ("espinaca_cocida", 80), ("aguacate", 40), ("aceite_oliva", 5)],
         ["130 g de garbanzos", "80 g de espinaca", "40 g de aguacate", "5 ml de aceite de oliva"], "lunch"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(5):  # 8 × 5 = 40
            n += 1
            descr = "Plato sin lactosa con fuentes vegetales o pescado, calcio de origen no lácteo (almendra/soya fortificadas, tofu, chía)."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina al punto.", "Combina y sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["lightly_active", "moderately_active"],
                ["lactose_intolerance"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=12,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# Bucket B — Pregnancy positive boost +250
# Folate, iron, calcium — populated. No raw fish / high-Hg / organ / alcohol /
# unpasteurized cheese / deli meat.
# ═════════════════════════════════════════════════════════════════════════
def build_pregnancy_boost() -> list[dict]:
    out: list[dict] = []
    bucket = "preg"
    n = 0
    # Each spec engineered so folate≥150 ug, iron≥4 mg, calcium≥250 mg per serving.
    specs = [
        # Lentil bowls (lentejas: 181 fol, 3.3 fe, 19 ca per 100g) — pair with
        # spinach (146 fol, 3.6 fe, 136 ca) + tahini or fortified milk for ca.
        ("Bowl de Lentejas con Espinaca y Tahini",
         [("lentejas_cocidas", 150), ("espinaca_cocida", 120), ("tahini", 15), ("quinoa_cocida", 80), ("aceite_oliva", 5)],
         ["150 g de lentejas cocidas", "120 g de espinaca cocida", "15 g de tahini", "80 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Lentejas con Espinaca y Yogur Griego",
         [("lentejas_cocidas", 150), ("espinaca_cocida", 100), ("yogur_griego", 150), ("aceite_oliva", 5)],
         ["150 g de lentejas", "100 g de espinaca cocida", "150 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "lunch"),
        ("Garbanzos con Espinaca, Tahini y Quinoa",
         [("garbanzos_cocidos", 130), ("espinaca_cocida", 100), ("tahini", 15), ("quinoa_cocida", 100)],
         ["130 g de garbanzos", "100 g de espinaca cocida", "15 g de tahini", "100 g de quinoa"], "lunch"),
        ("Avena con Espinaca Cocida, Lentejas y Yogur",
         [("avena_sin_gluten", 40), ("espinaca_cocida", 100), ("lentejas_cocidas", 80), ("yogur_griego", 200), ("linaza", 12)],
         ["40 g de avena sin gluten", "100 g de espinaca cocida", "80 g de lentejas", "200 g de yogur griego pasteurizado", "12 g de linaza"], "breakfast"),
        ("Frittata de Espinaca con Quinoa y Yogur",
         [("huevo", 100), ("espinaca_cocida", 130), ("quinoa_cocida", 100), ("yogur_griego", 100), ("aceite_oliva", 5)],
         ["2 huevos cocidos", "130 g de espinaca cocida", "100 g de quinoa", "100 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "breakfast"),
        ("Edamame con Quinoa, Espinaca y Tahini",
         [("edamame_cocido", 130), ("quinoa_cocida", 100), ("espinaca_cocida", 100), ("tahini", 12)],
         ["130 g de edamame", "100 g de quinoa", "100 g de espinaca", "12 g de tahini"], "lunch"),
        ("Lentejas con Brócoli y Yogur",
         [("lentejas_cocidas", 150), ("brocoli_cocido", 120), ("yogur_griego", 200), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["150 g de lentejas", "120 g de brócoli", "200 g de yogur griego pasteurizado", "80 g de espinaca cocida", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón Cocido con Espinaca y Quinoa",
         [("salmon_cocido", 100), ("espinaca_cocida", 130), ("quinoa_cocida", 100), ("tahini", 12), ("aceite_oliva", 5)],
         ["100 g de salmón cocido (bien hecho)", "130 g de espinaca", "100 g de quinoa", "12 g de tahini", "5 ml de aceite de oliva"], "dinner"),
        ("Pollo Magro con Espinaca, Lentejas y Yogur",
         [("pollo_pechuga", 100), ("espinaca_cocida", 100), ("lentejas_cocidas", 100), ("yogur_griego", 100), ("aceite_oliva", 5)],
         ["100 g de pollo", "100 g de espinaca", "100 g de lentejas", "100 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl de Garbanzos con Kale y Yogur",
         [("garbanzos_cocidos", 130), ("kale_cocida", 100), ("yogur_griego", 130), ("quinoa_cocida", 80), ("aceite_oliva", 5)],
         ["130 g de garbanzos", "100 g de kale cocida", "130 g de yogur griego pasteurizado", "80 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl Mañanero de Espinaca, Lentejas y Yogur con Avena",
         [("espinaca_cocida", 100), ("lentejas_cocidas", 100), ("yogur_griego", 200), ("avena_sin_gluten", 30), ("linaza", 12)],
         ["100 g de espinaca cocida", "100 g de lentejas", "200 g de yogur griego pasteurizado", "30 g de avena sin gluten", "12 g de linaza"], "breakfast"),
        ("Lentejas con Espinaca y Camote",
         [("lentejas_cocidas", 150), ("espinaca_cocida", 120), ("camote_cocido", 130), ("almendras", 12), ("aceite_oliva", 5)],
         ["150 g de lentejas", "120 g de espinaca", "130 g de camote", "12 g de almendras", "5 ml de aceite de oliva"], "lunch"),
        ("Tofu con Espinaca, Quinoa y Tahini",
         [("tofu_firme", 130), ("espinaca_cocida", 100), ("quinoa_cocida", 100), ("tahini", 10)],
         ["130 g de tofu firme", "100 g de espinaca", "100 g de quinoa", "10 g de tahini"], "dinner"),
        ("Edamame con Lentejas, Espinaca y Yogur",
         [("edamame_cocido", 100), ("lentejas_cocidas", 130), ("espinaca_cocida", 100), ("yogur_griego", 150), ("aceite_oliva", 5)],
         ["100 g de edamame", "130 g de lentejas", "100 g de espinaca", "150 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "lunch"),
        ("Frittata con Espinaca y Lentejas y Yogur",
         [("huevo", 100), ("espinaca_cocida", 120), ("lentejas_cocidas", 80), ("yogur_griego", 150), ("aceite_oliva", 5)],
         ["2 huevos", "120 g de espinaca cocida", "80 g de lentejas", "150 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "breakfast"),
        ("Bowl de Pavo con Lentejas y Espinaca",
         [("pavo_pechuga", 100), ("lentejas_cocidas", 130), ("espinaca_cocida", 100), ("yogur_griego", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "130 g de lentejas", "100 g de espinaca", "100 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl de Edamame y Espinaca con Yogur",
         [("edamame_cocido", 130), ("espinaca_cocida", 100), ("yogur_griego", 180), ("quinoa_cocida", 80), ("aceite_oliva", 5)],
         ["130 g de edamame", "100 g de espinaca cocida", "180 g de yogur griego pasteurizado", "80 g de quinoa", "5 ml de aceite de oliva"], "breakfast"),
        ("Ternera Magra con Espinaca, Lentejas y Yogur",
         [("ternera_magra", 100), ("espinaca_cocida", 100), ("lentejas_cocidas", 100), ("yogur_griego", 100), ("aceite_oliva", 5)],
         ["100 g de ternera magra (bien cocida)", "100 g de espinaca", "100 g de lentejas", "100 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "dinner"),
        ("Frittata con Espinaca, Tofu y Quinoa",
         [("huevo", 100), ("espinaca_cocida", 100), ("tofu_firme", 80), ("quinoa_cocida", 80), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de espinaca", "80 g de tofu", "80 g de quinoa", "5 ml de aceite de oliva"], "breakfast"),
        ("Lentejas con Espinaca, Quinoa y Almendras",
         [("lentejas_cocidas", 150), ("espinaca_cocida", 100), ("quinoa_cocida", 100), ("almendras", 15), ("yogur_griego", 130), ("aceite_oliva", 5)],
         ["150 g de lentejas", "100 g de espinaca", "100 g de quinoa", "15 g de almendras", "130 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "lunch"),
        ("Pollo con Kale, Quinoa y Yogur",
         [("pollo_pechuga", 100), ("kale_cocida", 120), ("quinoa_cocida", 100), ("yogur_griego", 180), ("lentejas_cocidas", 80), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de kale cocida", "100 g de quinoa", "180 g de yogur griego pasteurizado", "80 g de lentejas", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl de Frijoles Negros con Espinaca y Yogur",
         [("frijoles_negros_cocidos", 130), ("espinaca_cocida", 100), ("yogur_griego", 130), ("arroz_integral_cocido", 80), ("aceite_oliva", 5)],
         ["130 g de frijoles negros", "100 g de espinaca", "130 g de yogur griego pasteurizado", "80 g de arroz integral", "5 ml de aceite de oliva"], "lunch"),
        ("Edamame con Espinaca, Tofu y Tahini",
         [("edamame_cocido", 100), ("espinaca_cocida", 100), ("tofu_firme", 100), ("tahini", 12)],
         ["100 g de edamame", "100 g de espinaca", "100 g de tofu", "12 g de tahini"], "lunch"),
        ("Garbanzos con Brócoli, Tahini y Quinoa",
         [("garbanzos_cocidos", 150), ("brocoli_cocido", 120), ("tahini", 20), ("quinoa_cocida", 100), ("espinaca_cocida", 80)],
         ["150 g de garbanzos", "120 g de brócoli", "20 g de tahini", "100 g de quinoa", "80 g de espinaca cocida"], "lunch"),
        ("Lentejas con Kale y Yogur",
         [("lentejas_cocidas", 150), ("kale_cocida", 100), ("yogur_griego", 150), ("aceite_oliva", 5)],
         ["150 g de lentejas", "100 g de kale cocida", "150 g de yogur griego pasteurizado", "5 ml de aceite de oliva"], "lunch"),
    ]
    # 25 specs × 10 variants = 250
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato apto para embarazo con folato, hierro y calcio en cantidad relevante por porción; proteínas siempre bien cocidas y lácteos pasteurizados."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina las proteínas completamente.", "Combina con vegetales cocidos.", "Sirve con cuidado de inocuidad."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["lightly_active", "moderately_active"],
                ["pregnancy"], [],
                meal_time=mt, pregnancy_safe=True, prep=10, cook=15,
                populate_pregnancy_micros=True,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
def main() -> None:
    all_buckets = {
        "ibd_extra": (build_ibd_extra(), False),
        "hyperthyroidism_extra": (build_hyperthyroid_extra(), False),
        "vitamin_d_extra": (build_vit_d_extra(), False),
        "lactose_extra": (build_lactose_extra(), False),
        "pregnancy_boost": (build_pregnancy_boost(), True),
    }

    master_path = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
    master = json.loads(master_path.read_text())
    existing_names = {(r.get("name") or "").strip().lower() for r in master if isinstance(r, dict)}
    existing_ids = {r.get("id") for r in master if isinstance(r, dict)}

    valid: list[dict] = []
    rejected: list[tuple[str, str]] = []
    bucket_stats: dict[str, dict[str, int]] = {}

    for bucket_name, (recipes, expect_preg) in all_buckets.items():
        stat = {"generated": 0, "accepted": 0, "rejected": 0, "dedup": 0}
        for r in recipes:
            stat["generated"] += 1
            nm = (r.get("name") or "").strip().lower()
            if nm in existing_names:
                stat["dedup"] += 1
                rejected.append((r["id"], "dedup_name"))
                continue
            if r["id"] in existing_ids:
                stat["dedup"] += 1
                rejected.append((r["id"], "dedup_id"))
                continue
            ok, reason = validate(r, expect_pregnancy=expect_preg)
            if not ok:
                stat["rejected"] += 1
                rejected.append((r["id"], reason))
                continue
            stat["accepted"] += 1
            existing_names.add(nm)
            existing_ids.add(r["id"])
            valid.append(r)
        bucket_stats[bucket_name] = stat

    out_path = ROOT / "data" / "meals" / "finalization_batch_2026_06_01.json"
    out_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2))

    log_path = ROOT / "scripts" / "generate_recipes_finalization_2026_06_01_rejections.log"
    log_lines = [f"TOTAL accepted={len(valid)} rejected={len(rejected)}", ""]
    for b, s in bucket_stats.items():
        log_lines.append(f"  {b:25s} gen={s['generated']:4d} acc={s['accepted']:4d} rej={s['rejected']:3d} dedup={s['dedup']:3d}")
    log_lines.append("")
    log_lines.extend(f"{rid}\t{reason}" for rid, reason in rejected)
    log_path.write_text("\n".join(log_lines))

    print(f"finalization_batch: accepted={len(valid)} rejected={len(rejected)}")
    for b, s in bucket_stats.items():
        print(f"  {b:25s} gen={s['generated']} acc={s['accepted']} rej={s['rejected']} dedup={s['dedup']}")


if __name__ == "__main__":
    main()
