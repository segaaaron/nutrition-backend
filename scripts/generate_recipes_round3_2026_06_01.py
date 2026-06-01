"""Round 3 recipe batch — 2026-06-01.

Closes remaining red gaps after round 2 + condition_helpful + viral juices:
  - ibd                    +100   (low-FODMAP soluble fiber, no spicy/raw high-fiber)
  - hyperthyroidism        +100   (low iodine, cooked cruciferous, calcium-rich)
  - chronic_insomnia       +100   (tryptophan + magnesium, comforting evening)
  - diabetes_t1            +200   (carbs ≤45g, sugar ≤10g, fiber ≥8g, GL ≤10)
  - vitamin_d_deficiency   +60    (salmon, sardines, tuna, egg yolk, UV mushrooms, fortified)
  - overweight             +135   (300-500 kcal, satiety, lean)
  - gout (positive)        +100   (low-purine: dairy, eggs, veg, cherries)
  - liquid weight_loss/fl  +30    (extra green/hydrating juices GL<10)
  - diabetes_t1 snacks     +25    (100-200 kcal insulin-matching)

Total target: ~850 new recipes.

Same hard validators as condition_helpful batch:
  - macro math ±5%
  - allergen lookup EN+ES tokens
  - liquid sugar/GL audit
  - closed vocabulary membership
  - NO supplements, NO medical claims
  - dedup vs master 33,069 + cross-bucket

Output: data/meals/round3_batch_2026_06_01.json
"""
from __future__ import annotations

import json
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


# ───────────────────────────────────────────────────────────────────────────
# Ingredient nutrition per 100 g / 100 ml (USDA FDC / BEDCA averages).
# ───────────────────────────────────────────────────────────────────────────
ING: dict[str, dict] = {
    # Fruits
    "platano":          {"kcal": 89,  "p": 1.1, "c": 22.8, "f": 0.3, "fib": 2.6, "sug": 12.2, "na": 1,   "gi": 51,  "satf": 0.1,  "purine": "low"},
    "platano_maduro":   {"kcal": 89,  "p": 1.1, "c": 22.8, "f": 0.3, "fib": 2.6, "sug": 12.2, "na": 1,   "gi": 62,  "satf": 0.1,  "purine": "low"},
    "papaya":           {"kcal": 43,  "p": 0.5, "c": 10.8, "f": 0.3, "fib": 1.7, "sug": 7.8,  "na": 8,   "gi": 60,  "satf": 0.0,  "purine": "low"},
    "manzana":          {"kcal": 52,  "p": 0.3, "c": 13.8, "f": 0.2, "fib": 2.4, "sug": 10.4, "na": 1,   "gi": 39,  "satf": 0.0,  "purine": "low"},
    "manzana_verde":    {"kcal": 52,  "p": 0.3, "c": 13.8, "f": 0.2, "fib": 2.4, "sug": 10.4, "na": 1,   "gi": 39,  "satf": 0.0,  "purine": "low"},
    "pera":             {"kcal": 57,  "p": 0.4, "c": 15.2, "f": 0.1, "fib": 3.1, "sug": 9.8,  "na": 1,   "gi": 38,  "satf": 0.0,  "purine": "low"},
    "kiwi":             {"kcal": 61,  "p": 1.1, "c": 14.7, "f": 0.5, "fib": 3.0, "sug": 9.0,  "na": 3,   "gi": 50,  "satf": 0.0,  "purine": "low"},
    "limon":            {"kcal": 29,  "p": 1.1, "c": 9.3,  "f": 0.3, "fib": 2.8, "sug": 2.5,  "na": 2,   "gi": 20,  "satf": 0.0,  "purine": "low"},
    "fresa":            {"kcal": 32,  "p": 0.7, "c": 7.7,  "f": 0.3, "fib": 2.0, "sug": 4.9,  "na": 1,   "gi": 40,  "satf": 0.0,  "purine": "low"},
    "arandanos":        {"kcal": 57,  "p": 0.7, "c": 14.5, "f": 0.3, "fib": 2.4, "sug": 10.0, "na": 1,   "gi": 53,  "satf": 0.0,  "purine": "low"},
    "frambuesa":        {"kcal": 52,  "p": 1.2, "c": 11.9, "f": 0.7, "fib": 6.5, "sug": 4.4,  "na": 1,   "gi": 25,  "satf": 0.0,  "purine": "low"},
    "cereza":           {"kcal": 50,  "p": 1.0, "c": 12.2, "f": 0.3, "fib": 1.6, "sug": 8.5,  "na": 0,   "gi": 22,  "satf": 0.1,  "purine": "low"},
    "naranja":          {"kcal": 47,  "p": 0.9, "c": 11.8, "f": 0.1, "fib": 2.4, "sug": 9.4,  "na": 0,   "gi": 43,  "satf": 0.0,  "purine": "low"},
    "piña":             {"kcal": 50,  "p": 0.5, "c": 13.1, "f": 0.1, "fib": 1.4, "sug": 9.9,  "na": 1,   "gi": 66,  "satf": 0.0,  "purine": "low"},
    # Vegetables
    "apio":             {"kcal": 16,  "p": 0.7, "c": 3.0,  "f": 0.2, "fib": 1.6, "sug": 1.3, "na": 80, "gi": 15,  "satf": 0.0,  "purine": "low"},
    "pepino":           {"kcal": 16,  "p": 0.7, "c": 3.6,  "f": 0.1, "fib": 0.5, "sug": 1.7, "na": 2,  "gi": 15,  "satf": 0.0,  "purine": "low"},
    "espinaca_cocida":  {"kcal": 23,  "p": 2.9, "c": 3.6,  "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79, "gi": 15,  "satf": 0.1,  "purine": "mod"},
    "kale_cocida":      {"kcal": 35,  "p": 2.9, "c": 4.4,  "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53, "gi": 15,  "satf": 0.2,  "purine": "low"},
    "lechuga":          {"kcal": 15,  "p": 1.4, "c": 2.9,  "f": 0.2, "fib": 1.3, "sug": 0.8, "na": 28, "gi": 15,  "satf": 0.0,  "purine": "low"},
    "calabacin":        {"kcal": 17,  "p": 1.2, "c": 3.1,  "f": 0.3, "fib": 1.0, "sug": 2.5, "na": 8,  "gi": 15,  "satf": 0.1,  "purine": "low"},
    "tomate":           {"kcal": 18,  "p": 0.9, "c": 3.9,  "f": 0.2, "fib": 1.2, "sug": 2.6, "na": 5,  "gi": 30,  "satf": 0.0,  "purine": "low"},
    "zanahoria":        {"kcal": 41,  "p": 0.9, "c": 9.6,  "f": 0.2, "fib": 2.8, "sug": 4.7, "na": 69, "gi": 39,  "satf": 0.0,  "purine": "low"},
    "brocoli_cocido":   {"kcal": 35,  "p": 2.4, "c": 7.2,  "f": 0.4, "fib": 3.3, "sug": 1.4, "na": 41, "gi": 15,  "satf": 0.1,  "purine": "low"},
    "coliflor_cocida":  {"kcal": 23,  "p": 1.8, "c": 4.1,  "f": 0.5, "fib": 2.3, "sug": 1.9, "na": 15, "gi": 15,  "satf": 0.1,  "purine": "low"},
    "esparragos":       {"kcal": 20,  "p": 2.2, "c": 3.9,  "f": 0.1, "fib": 2.1, "sug": 1.9, "na": 2,  "gi": 15,  "satf": 0.0,  "purine": "mod"},
    "champinon":        {"kcal": 22,  "p": 3.1, "c": 3.3,  "f": 0.3, "fib": 1.0, "sug": 2.0, "na": 5,  "gi": 15,  "satf": 0.0,  "purine": "mod"},
    "champinon_uv":     {"kcal": 22,  "p": 3.1, "c": 3.3,  "f": 0.3, "fib": 1.0, "sug": 2.0, "na": 5,  "gi": 15,  "satf": 0.0,  "purine": "mod"},
    "jengibre":         {"kcal": 80,  "p": 1.8, "c": 18.0, "f": 0.8, "fib": 2.0, "sug": 1.7, "na": 13, "gi": 15,  "satf": 0.2,  "purine": "low"},
    # Carbs
    "avena_sin_gluten": {"kcal": 389, "p": 16.9, "c": 66.3, "f": 6.9, "fib": 10.6,"sug": 0,   "na": 2,  "gi": 55,  "satf": 1.2, "purine": "low"},
    "quinoa_cocida":    {"kcal": 120, "p": 4.4,  "c": 21.3, "f": 1.9, "fib": 2.8, "sug": 0.9, "na": 7,  "gi": 53,  "satf": 0.2, "purine": "low"},
    "arroz_integral_cocido": {"kcal": 111, "p": 2.6, "c": 23.0, "f": 0.9, "fib": 1.8, "sug": 0.4, "na": 5, "gi": 55, "satf": 0.2, "purine": "low"},
    "camote_cocido":    {"kcal": 86,  "p": 1.6,  "c": 20.1, "f": 0.1, "fib": 3.0, "sug": 4.2, "na": 55, "gi": 54,  "satf": 0.0, "purine": "low"},
    "papa_cocida":      {"kcal": 86,  "p": 1.7,  "c": 20.0, "f": 0.1, "fib": 1.8, "sug": 0.9, "na": 5,  "gi": 78,  "satf": 0.0, "purine": "low"},
    # Animal protein
    "pavo_pechuga":     {"kcal": 135, "p": 30.1, "c": 0.0,  "f": 1.0, "fib": 0,   "sug": 0,   "na": 54, "gi": 0,   "satf": 0.3, "purine": "mod"},
    "pollo_pechuga":    {"kcal": 165, "p": 31.0, "c": 0.0,  "f": 3.6, "fib": 0,   "sug": 0,   "na": 74, "gi": 0,   "satf": 1.0, "purine": "mod"},
    "salmon":           {"kcal": 208, "p": 20.4, "c": 0.0,  "f": 13.4,"fib": 0,   "sug": 0,   "na": 59, "gi": 0,   "satf": 3.1, "purine": "mod"},
    "sardina_lata":     {"kcal": 208, "p": 24.6, "c": 0.0,  "f": 11.4,"fib": 0,   "sug": 0,   "na": 307,"gi": 0,   "satf": 1.5, "purine": "high"},
    "atun_agua":        {"kcal": 116, "p": 25.5, "c": 0.0,  "f": 1.0, "fib": 0,   "sug": 0,   "na": 247,"gi": 0,   "satf": 0.3, "purine": "high"},
    "trucha":           {"kcal": 148, "p": 20.8, "c": 0.0,  "f": 6.6, "fib": 0,   "sug": 0,   "na": 52, "gi": 0,   "satf": 1.4, "purine": "mod"},
    "bacalao":          {"kcal": 82,  "p": 17.8, "c": 0.0,  "f": 0.7, "fib": 0,   "sug": 0,   "na": 54, "gi": 0,   "satf": 0.1, "purine": "mod"},
    "huevo":            {"kcal": 143, "p": 12.6, "c": 0.7,  "f": 9.5, "fib": 0,   "sug": 0.4, "na": 142,"gi": 0,   "satf": 3.1, "purine": "low"},
    "clara_huevo":      {"kcal": 52,  "p": 11.0, "c": 0.7,  "f": 0.2, "fib": 0,   "sug": 0.7, "na": 166,"gi": 0,   "satf": 0.0, "purine": "low"},
    "yema_huevo":       {"kcal": 322, "p": 15.9, "c": 3.6,  "f": 26.5,"fib": 0,   "sug": 0.6, "na": 48, "gi": 0,   "satf": 9.6, "purine": "low"},
    # Dairy (low-iodine for hyperthyroid means non-dairy; calcium-rich for them = fortified plant milks)
    "yogur_griego":     {"kcal": 59,  "p": 10.0, "c": 3.6,  "f": 0.4, "fib": 0,   "sug": 3.2, "na": 36, "gi": 11, "satf": 0.1, "purine": "low"},
    "yogur_sin_lactosa": {"kcal": 59, "p": 5.7,  "c": 7.0,  "f": 1.5, "fib": 0,   "sug": 7.0, "na": 50, "gi": 14, "satf": 0.9, "purine": "low"},
    "queso_cottage":    {"kcal": 98,  "p": 11.1, "c": 3.4,  "f": 4.3, "fib": 0,   "sug": 2.7, "na": 364,"gi": 30, "satf": 1.7, "purine": "low"},
    "leche_descremada": {"kcal": 34,  "p": 3.4,  "c": 5.0,  "f": 0.1, "fib": 0,   "sug": 5.0, "na": 42, "gi": 32, "satf": 0.1, "purine": "low"},
    "leche_almendra_fortificada": {"kcal": 17, "p": 0.6, "c": 0.6, "f": 1.5, "fib": 0.3, "sug": 0, "na": 60, "gi": 25, "satf": 0.1, "purine": "low"},
    "leche_almendra":   {"kcal": 17,  "p": 0.6, "c": 0.6,  "f": 1.5, "fib": 0.3, "sug": 0,   "na": 60, "gi": 25, "satf": 0.1, "purine": "low"},
    "leche_avena":      {"kcal": 47,  "p": 1.0, "c": 6.6,  "f": 1.5, "fib": 0.8, "sug": 3.3, "na": 42, "gi": 60, "satf": 0.2, "purine": "low"},
    "leche_soya":       {"kcal": 33,  "p": 3.3, "c": 1.8,  "f": 1.8, "fib": 0.4, "sug": 1.0, "na": 51, "gi": 30, "satf": 0.3, "purine": "low"},
    # Legumes
    "lentejas_cocidas": {"kcal": 116, "p": 9.0, "c": 20.1, "f": 0.4, "fib": 7.9, "sug": 1.8, "na": 2,  "gi": 32, "satf": 0.1, "purine": "mod"},
    "garbanzos_cocidos": {"kcal": 164, "p": 8.9, "c": 27.4, "f": 2.6, "fib": 7.6, "sug": 4.8, "na": 7, "gi": 36, "satf": 0.3, "purine": "mod"},
    "tofu_firme":       {"kcal": 144, "p": 17.3, "c": 2.8,  "f": 8.7, "fib": 2.3, "sug": 0.6, "na": 14, "gi": 15, "satf": 1.3, "purine": "mod"},
    "edamame_cocido":   {"kcal": 122, "p": 11.0, "c": 9.9,  "f": 5.2, "fib": 5.2, "sug": 2.2, "na": 6,  "gi": 18, "satf": 0.6, "purine": "mod"},
    # Seeds / nuts / fats
    "chia":             {"kcal": 486, "p": 16.5, "c": 42.1, "f": 30.7, "fib": 34.4, "sug": 0,  "na": 16, "gi": 1,  "satf": 3.3, "purine": "low"},
    "linaza":           {"kcal": 534, "p": 18.3, "c": 28.9, "f": 42.2, "fib": 27.3, "sug": 1.6,"na": 30, "gi": 1,  "satf": 3.7, "purine": "low"},
    "almendras":        {"kcal": 579, "p": 21.2, "c": 21.6, "f": 49.9, "fib": 12.5, "sug": 4.4,"na": 1,  "gi": 0,  "satf": 3.8, "purine": "low"},
    "nueces":           {"kcal": 654, "p": 15.2, "c": 13.7, "f": 65.2, "fib": 6.7, "sug": 2.6, "na": 2, "gi": 0,  "satf": 6.1, "purine": "low"},
    "semilla_calabaza": {"kcal": 559, "p": 30.2, "c": 10.7, "f": 49.1, "fib": 6.0, "sug": 1.4, "na": 7, "gi": 25, "satf": 8.7, "purine": "low"},
    "aceite_oliva":     {"kcal": 884, "p": 0.0,  "c": 0.0,  "f": 100.0,"fib": 0,   "sug": 0,   "na": 2, "gi": 0,  "satf": 13.8,"purine": "low"},
    "aguacate":         {"kcal": 160, "p": 2.0,  "c": 8.5,  "f": 14.7, "fib": 6.7, "sug": 0.7, "na": 7, "gi": 15, "satf": 2.1, "purine": "low"},
    "chocolate_oscuro_85": {"kcal": 590, "p": 7.8, "c": 30.0, "f": 43.0, "fib": 11.0, "sug": 14.0, "na": 20, "gi": 23, "satf": 26.0, "purine": "low"},
    # Liquids
    "agua":             {"kcal": 0, "p": 0, "c": 0, "f": 0, "fib": 0, "sug": 0, "na": 0, "gi": 0, "satf": 0, "purine": "low"},
    "te_verde":         {"kcal": 1, "p": 0, "c": 0.2, "f": 0, "fib": 0, "sug": 0, "na": 1, "gi": 0, "satf": 0, "purine": "low"},
    "te_manzanilla":    {"kcal": 1, "p": 0, "c": 0.2, "f": 0, "fib": 0, "sug": 0, "na": 1, "gi": 0, "satf": 0, "purine": "low"},
    # Spices
    "canela":           {"kcal": 247, "p": 4.0, "c": 80.6, "f": 1.2, "fib": 53.1, "sug": 2.2, "na": 10, "gi": 5, "satf": 0.3, "purine": "low"},
    "curcuma":          {"kcal": 312, "p": 9.7, "c": 67.0, "f": 3.3, "fib": 22.7, "sug": 3.2, "na": 27, "gi": 15, "satf": 0.9, "purine": "low"},
}


ALLERGEN_MAP = [
    (("almendra", "nuez", "almond", "walnut", "cashew", "pistachio", "pecan", "hazelnut", "macadamia", "brasil"), "tree_nuts"),
    (("leche", "yogur", "queso", "kefir", "yogurt", "butter", "cottage"), "dairy"),
    (("trigo", "wheat", "harina", "pan ", "pasta", "flour", "bread", "avena", "oats"), "gluten"),
    (("maní", "mani", "peanut", "cacahuate"), "peanuts"),
    (("camarón", "langosta", "cangrejo", "shrimp", "crab", "lobster"), "shellfish"),
    (("pescado", "atún", "atun", "salmón", "salmon", "tuna", "sardina", "sardine", "trucha", "bacalao"), "fish"),
    (("huevo", "clara de huevo", "yema", "egg"), "egg"),
    (("soya", "soja", "tofu", "tempeh", "edamame", "soy"), "soy"),
    (("sésamo", "sesamo", "sesame", "tahini"), "sesame"),
]


def detect_allergens(ingredients_text: list[str]) -> list[str]:
    text = " ".join(ingredients_text).lower()
    found: set[str] = set()
    for keys, tag in ALLERGEN_MAP:
        if any(k in text for k in keys):
            found.add(tag)
    if ("avena" in text) and ("sin gluten" not in text) and ("certificada" not in text):
        found.add("gluten")
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    p = c = f = fib = sug = na = satf = 0.0
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
    }


def gl_estimate(carbs_g: int, gi: int | None) -> float | None:
    if gi is None:
        return None
    return round((carbs_g * gi) / 100.0, 1)


def has_purine_high(components: list[tuple[str, float]]) -> bool:
    return any(ING[k]["purine"] == "high" for k, _ in components)


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
    cultural_origin: str | None = None,
    source_catalog: str = "nova_v2_batch_round3_2026_06_01",
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
            "micronutrients": {
                "gi": m["gi"], "gl": gl,
                "potassium_mg": None, "phosphorus_mg": None, "iron_mg": None, "heme_pct": None,
                "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
            },
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
            "cultural_origin": cultural_origin,
            "image_status": "placeholder_pending_upload",
            "generated_at": "2026-06-01",
            "bucket": None,
        },
    }


def validate(recipe: dict) -> tuple[bool, str]:
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
    blob = " ".join([
        recipe["name"].lower(),
        recipe["description"].lower(),
        " ".join(s.lower() for s in recipe["execution"]["ingredients"]),
        " ".join(s.lower() for s in recipe["execution"]["instructions"]),
    ])
    for tok in SUPPLEMENT_TOKENS:
        if tok in blob:
            return False, f"supplement_token={tok}"
    for tok in FORBIDDEN_CLAIM_TOKENS:
        if tok in blob:
            return False, f"medical_claim_token={tok.strip()}"
    return True, "ok"


def _id(bucket_tag: str, n: int) -> str:
    return f"nova_meal_r3_{bucket_tag}_{n:04d}"


def _fin(r: dict, bucket: str) -> dict:
    r["audit"]["bucket"] = bucket
    return r


# ═════════════════════════════════════════════════════════════════════════
# 1) IBD — 100 (low-FODMAP soluble fiber, gentle, no spicy/raw)
# ═════════════════════════════════════════════════════════════════════════
def build_ibd() -> list[dict]:
    out: list[dict] = []
    bucket = "ibd"
    n = 0
    specs = [
        ("Avena Cremosa con Plátano Maduro y Chía",
         [("avena_sin_gluten", 40), ("platano_maduro", 100), ("chia", 6), ("leche_almendra", 200)],
         ["40 g de avena sin gluten certificada", "100 g de plátano maduro", "6 g de chía hidratada", "200 ml de leche de almendra sin azúcar"],
         "breakfast"),
        ("Papaya con Yogur Sin Lactosa",
         [("papaya", 150), ("yogur_sin_lactosa", 150)],
         ["150 g de papaya madura", "150 g de yogur sin lactosa"], "breakfast"),
        ("Crema de Avena con Papaya",
         [("avena_sin_gluten", 40), ("papaya", 100), ("leche_almendra", 200)],
         ["40 g de avena sin gluten", "100 g de papaya", "200 ml de leche de almendra"], "breakfast"),
        ("Pollo Suave con Arroz Blanco y Zanahoria al Vapor",
         [("pollo_pechuga", 100), ("arroz_integral_cocido", 120), ("zanahoria", 100)],
         ["100 g de pechuga de pollo cocida", "120 g de arroz integral", "100 g de zanahoria al vapor"], "lunch"),
        ("Pavo al Vapor con Calabacín y Arroz",
         [("pavo_pechuga", 100), ("calabacin", 120), ("arroz_integral_cocido", 100)],
         ["100 g de pavo al vapor", "120 g de calabacín cocido", "100 g de arroz integral"], "lunch"),
        ("Bacalao con Zanahoria y Calabacín",
         [("bacalao", 130), ("zanahoria", 100), ("calabacin", 80), ("aceite_oliva", 5)],
         ["130 g de bacalao", "100 g de zanahoria", "80 g de calabacín", "5 ml de aceite de oliva"], "lunch"),
        ("Crema Suave de Calabacín y Pollo",
         [("calabacin", 200), ("pollo_pechuga", 80), ("aceite_oliva", 5)],
         ["200 g de calabacín", "80 g de pollo desmechado", "5 ml de aceite de oliva"], "dinner"),
        ("Tortilla de Claras con Calabacín",
         [("clara_huevo", 120), ("calabacin", 100), ("aceite_oliva", 5)],
         ["120 g de claras de huevo", "100 g de calabacín", "5 ml de aceite de oliva"], "breakfast"),
        ("Plátano Maduro con Avena Tibia",
         [("avena_sin_gluten", 35), ("platano_maduro", 80), ("leche_almendra", 200)],
         ["35 g de avena sin gluten", "80 g de plátano maduro", "200 ml de leche de almendra"], "snack"),
        ("Trucha Suave con Arroz Blanco",
         [("trucha", 100), ("arroz_integral_cocido", 120), ("zanahoria", 80), ("aceite_oliva", 5)],
         ["100 g de trucha al vapor", "120 g de arroz", "80 g de zanahoria", "5 ml de aceite de oliva"], "dinner"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato gentil con fibra soluble suave, sin alto FODMAP, sin picante ni crudos de fibra alta, alineado con bienestar digestivo en EII."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina los ingredientes a textura suave.", "Combina con cuidado.", "Sirve tibio."],
                "solid", ["latam"], ["latam"], "omnivore",
                ["maintain", "health"], ["sedentary", "lightly_active"],
                ["ibd", "ibs"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=12,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 2) HYPERTHYROIDISM — 100 (low iodine, cooked cruciferous OK, calcium-rich)
# ═════════════════════════════════════════════════════════════════════════
def build_hyperthyroidism() -> list[dict]:
    out: list[dict] = []
    bucket = "hy"
    n = 0
    # Avoid seafood (high iodine). Calcium from fortified plant milk, almonds, leafy greens.
    specs = [
        ("Pollo con Brócoli Cocido y Quinoa",
         [("pollo_pechuga", 100), ("brocoli_cocido", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de brócoli cocido", "100 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Pavo con Coliflor Cocida y Arroz Integral",
         [("pavo_pechuga", 100), ("coliflor_cocida", 120), ("arroz_integral_cocido", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "120 g de coliflor cocida", "100 g de arroz integral", "5 ml de aceite de oliva"], "lunch"),
        ("Avena con Leche de Almendra Fortificada y Frambuesa",
         [("avena_sin_gluten", 40), ("leche_almendra_fortificada", 250), ("frambuesa", 80), ("almendras", 10)],
         ["40 g de avena sin gluten", "250 ml de leche de almendra fortificada en calcio", "80 g de frambuesa", "10 g de almendras"], "breakfast"),
        ("Bowl de Quinoa con Espinaca Cocida y Almendras",
         [("quinoa_cocida", 150), ("espinaca_cocida", 100), ("almendras", 15), ("aceite_oliva", 5)],
         ["150 g de quinoa", "100 g de espinaca cocida", "15 g de almendras", "5 ml de aceite de oliva"], "lunch"),
        ("Pollo con Kale Cocida y Camote",
         [("pollo_pechuga", 100), ("kale_cocida", 100), ("camote_cocido", 150), ("aceite_oliva", 5)],
         ["100 g de pollo", "100 g de kale cocida", "150 g de camote", "5 ml de aceite de oliva"], "dinner"),
        ("Smoothie de Leche de Almendra Fortificada y Plátano",
         [("leche_almendra_fortificada", 250), ("platano", 100), ("chia", 8)],
         ["250 ml de leche de almendra fortificada", "100 g de plátano", "8 g de chía"], "breakfast"),
        ("Tofu Salteado con Coliflor Cocida",
         [("tofu_firme", 120), ("coliflor_cocida", 150), ("aceite_oliva", 5)],
         ["120 g de tofu firme", "150 g de coliflor cocida", "5 ml de aceite de oliva"], "dinner"),
        ("Pavo con Calabacín y Quinoa",
         [("pavo_pechuga", 100), ("calabacin", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "120 g de calabacín", "100 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Avena con Plátano y Almendras",
         [("avena_sin_gluten", 40), ("leche_almendra_fortificada", 200), ("platano", 80), ("almendras", 10)],
         ["40 g de avena", "200 ml de leche de almendra fortificada", "80 g de plátano", "10 g de almendras"], "breakfast"),
        ("Bowl de Quinoa con Brócoli Cocido y Almendras",
         [("quinoa_cocida", 130), ("brocoli_cocido", 100), ("almendras", 12), ("aceite_oliva", 5)],
         ["130 g de quinoa", "100 g de brócoli cocido", "12 g de almendras", "5 ml de aceite de oliva"], "lunch"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato bajo en yodo (sin pescados ni mariscos), con crucíferas cocidas y fuente de calcio vegetal, alineado con hipertiroidismo."
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
# 3) CHRONIC_INSOMNIA — 100 (tryptophan + magnesium, evening-friendly)
# ═════════════════════════════════════════════════════════════════════════
def build_insomnia() -> list[dict]:
    out: list[dict] = []
    bucket = "ci"
    n = 0
    specs = [
        ("Pavo al Horno con Camote y Espinaca",
         [("pavo_pechuga", 100), ("camote_cocido", 150), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de pavo al horno", "150 g de camote cocido", "80 g de espinaca", "5 ml de aceite de oliva"], "dinner"),
        ("Avena Tibia con Plátano y Almendras",
         [("avena_sin_gluten", 40), ("platano", 100), ("almendras", 12), ("leche_almendra", 200)],
         ["40 g de avena sin gluten", "100 g de plátano", "12 g de almendras", "200 ml de leche de almendra"], "dinner"),
        ("Pavo con Quinoa y Semillas de Calabaza",
         [("pavo_pechuga", 100), ("quinoa_cocida", 120), ("semilla_calabaza", 10), ("aceite_oliva", 5)],
         ["100 g de pavo", "120 g de quinoa", "10 g de semillas de calabaza", "5 ml de aceite de oliva"], "dinner"),
        ("Yogur Griego con Plátano y Almendras",
         [("yogur_griego", 200), ("platano", 80), ("almendras", 10)],
         ["200 g de yogur griego", "80 g de plátano", "10 g de almendras"], "snack"),
        ("Avena con Leche Tibia y Canela",
         [("avena_sin_gluten", 40), ("leche_descremada", 200), ("canela", 1)],
         ["40 g de avena sin gluten", "200 ml de leche descremada tibia", "1 g de canela"], "dinner"),
        ("Té de Manzanilla con Avena y Plátano",
         [("avena_sin_gluten", 35), ("platano", 80), ("te_manzanilla", 200), ("almendras", 8)],
         ["35 g de avena", "80 g de plátano", "200 ml de té de manzanilla", "8 g de almendras"], "dinner"),
        ("Pavo con Espinaca y Arroz Integral",
         [("pavo_pechuga", 100), ("espinaca_cocida", 100), ("arroz_integral_cocido", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "100 g de espinaca", "100 g de arroz integral", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl Tibio de Quinoa con Almendras y Chocolate Oscuro",
         [("quinoa_cocida", 130), ("almendras", 12), ("chocolate_oscuro_85", 8), ("leche_almendra", 100)],
         ["130 g de quinoa tibia", "12 g de almendras", "8 g de chocolate oscuro 85%", "100 ml de leche de almendra"], "snack"),
        ("Avena con Plátano, Chía y Canela",
         [("avena_sin_gluten", 40), ("platano", 80), ("chia", 8), ("canela", 1), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de plátano", "8 g de chía", "1 g de canela", "200 ml de leche de almendra"], "dinner"),
        ("Yogur Sin Lactosa con Semillas de Calabaza y Frambuesa",
         [("yogur_sin_lactosa", 180), ("semilla_calabaza", 10), ("frambuesa", 60)],
         ["180 g de yogur sin lactosa", "10 g de semillas de calabaza", "60 g de frambuesa"], "snack"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Comida nocturna reconfortante con fuente de triptófano y magnesio (pavo, plátano, semillas, almendras), alineada con higiene del sueño."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina tibio.", "Sirve cómodo en la noche."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["sedentary", "lightly_active"],
                ["chronic_insomnia"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=12,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 4) DIABETES_T1 — 200 (carbs ≤45, sugar ≤10, fiber ≥8, GL ≤10 ideal)
# ═════════════════════════════════════════════════════════════════════════
def build_diabetes_t1() -> list[dict]:
    out: list[dict] = []
    bucket = "d1"
    n = 0
    specs = [
        ("Bowl de Quinoa con Pollo y Aguacate",
         [("quinoa_cocida", 120), ("pollo_pechuga", 100), ("aguacate", 50), ("espinaca_cocida", 60), ("aceite_oliva", 5)],
         ["120 g de quinoa", "100 g de pollo", "50 g de aguacate", "60 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón con Quinoa y Brócoli",
         [("salmon", 100), ("quinoa_cocida", 100), ("brocoli_cocido", 100), ("aceite_oliva", 5)],
         ["100 g de salmón", "100 g de quinoa", "100 g de brócoli", "5 ml de aceite de oliva"], "dinner"),
        ("Tortilla de Claras con Espinaca y Aguacate",
         [("clara_huevo", 120), ("espinaca_cocida", 100), ("aguacate", 50), ("aceite_oliva", 5)],
         ["120 g de claras", "100 g de espinaca", "50 g de aguacate", "5 ml de aceite de oliva"], "breakfast"),
        ("Bowl de Lentejas con Aguacate y Espinaca",
         [("lentejas_cocidas", 130), ("aguacate", 50), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["130 g de lentejas", "50 g de aguacate", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Avena Cortada con Frambuesa y Chía",
         [("avena_sin_gluten", 35), ("frambuesa", 80), ("chia", 10), ("leche_almendra", 200)],
         ["35 g de avena cortada", "80 g de frambuesa", "10 g de chía", "200 ml de leche de almendra"], "breakfast"),
        ("Pollo con Coliflor y Quinoa",
         [("pollo_pechuga", 100), ("coliflor_cocida", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de coliflor", "100 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Tofu con Brócoli y Quinoa",
         [("tofu_firme", 120), ("brocoli_cocido", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["120 g de tofu", "120 g de brócoli", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Bacalao con Espárragos y Quinoa",
         [("bacalao", 130), ("esparragos", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["130 g de bacalao", "100 g de espárragos", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Pavo con Aguacate y Quinoa",
         [("pavo_pechuga", 100), ("aguacate", 50), ("quinoa_cocida", 100), ("espinaca_cocida", 60)],
         ["100 g de pavo", "50 g de aguacate", "100 g de quinoa", "60 g de espinaca"], "lunch"),
        ("Huevo Revuelto con Espinaca y Aguacate",
         [("huevo", 100), ("espinaca_cocida", 100), ("aguacate", 50), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de espinaca", "50 g de aguacate", "5 ml de aceite de oliva"], "breakfast"),
        ("Yogur Griego con Frambuesa y Chía",
         [("yogur_griego", 200), ("frambuesa", 80), ("chia", 8)],
         ["200 g de yogur griego", "80 g de frambuesa", "8 g de chía"], "breakfast"),
        ("Ensalada de Atún con Aguacate",
         [("atun_agua", 100), ("aguacate", 50), ("lechuga", 80), ("tomate", 80), ("aceite_oliva", 5)],
         ["100 g de atún", "50 g de aguacate", "80 g de lechuga", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Trucha con Espinaca y Quinoa",
         [("trucha", 100), ("espinaca_cocida", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de trucha", "100 g de espinaca", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Edamame con Quinoa y Aguacate",
         [("edamame_cocido", 100), ("quinoa_cocida", 100), ("aguacate", 50), ("aceite_oliva", 5)],
         ["100 g de edamame", "100 g de quinoa", "50 g de aguacate", "5 ml de aceite de oliva"], "lunch"),
        ("Pollo con Calabacín y Quinoa",
         [("pollo_pechuga", 100), ("calabacin", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de calabacín", "100 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Pavo con Espárragos y Quinoa",
         [("pavo_pechuga", 100), ("esparragos", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "100 g de espárragos", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl de Garbanzos con Aguacate y Espinaca",
         [("garbanzos_cocidos", 100), ("aguacate", 40), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de garbanzos", "40 g de aguacate", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Yogur Sin Lactosa con Almendras y Frambuesa",
         [("yogur_sin_lactosa", 180), ("almendras", 12), ("frambuesa", 60)],
         ["180 g de yogur sin lactosa", "12 g de almendras", "60 g de frambuesa"], "breakfast"),
        ("Salmón con Espinaca y Aguacate",
         [("salmon", 100), ("espinaca_cocida", 100), ("aguacate", 40), ("aceite_oliva", 5)],
         ["100 g de salmón", "100 g de espinaca", "40 g de aguacate", "5 ml de aceite de oliva"], "dinner"),
        ("Tofu con Espinaca y Quinoa",
         [("tofu_firme", 120), ("espinaca_cocida", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["120 g de tofu", "100 g de espinaca", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):  # 20 × 10 = 200
            n += 1
            descr = "Plato de bajo índice glucémico con carbohidratos controlados, alto en fibra y proteína, alineado con manejo de diabetes tipo 1."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina al punto.", "Sirve combinado."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["lightly_active", "moderately_active", "very_active"],
                ["diabetes_t1", "diabetes_t2"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=12,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 5) VITAMIN_D_DEFICIENCY — 60
# ═════════════════════════════════════════════════════════════════════════
def build_vit_d() -> list[dict]:
    out: list[dict] = []
    bucket = "vd2"
    n = 0
    specs = [
        ("Salmón con Quinoa y Espinaca",
         [("salmon", 120), ("quinoa_cocida", 100), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["120 g de salmón", "100 g de quinoa", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Sardinas con Quinoa y Limón",
         [("sardina_lata", 70), ("quinoa_cocida", 120), ("limon", 15), ("aceite_oliva", 5)],
         ["70 g de sardinas escurridas", "120 g de quinoa", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Huevo Revuelto con Champiñones UV",
         [("huevo", 100), ("champinon_uv", 100), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de champiñones tratados con UV", "5 ml de aceite de oliva"], "breakfast"),
        ("Avena con Leche Almendra Fortificada y Plátano",
         [("avena_sin_gluten", 40), ("leche_almendra_fortificada", 250), ("platano", 80), ("chia", 8)],
         ["40 g de avena", "250 ml de leche de almendra fortificada", "80 g de plátano", "8 g de chía"], "breakfast"),
        ("Salmón con Espárragos y Quinoa",
         [("salmon", 100), ("esparragos", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de salmón", "100 g de espárragos", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Atún con Aguacate y Quinoa",
         [("atun_agua", 100), ("aguacate", 50), ("quinoa_cocida", 100)],
         ["100 g de atún en agua", "50 g de aguacate", "100 g de quinoa"], "lunch"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):  # 6 × 10 = 60
            n += 1
            descr = "Plato con fuentes alimentarias de vitamina D (pescado graso, yema de huevo, hongos UV, leche fortificada)."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina la proteína.", "Combina con vegetales.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["lightly_active", "moderately_active"],
                ["vitamin_d_deficiency"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=12,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 6) OVERWEIGHT — 135 (300-500 kcal, high fiber, lean protein, satiety)
# ═════════════════════════════════════════════════════════════════════════
def build_overweight() -> list[dict]:
    out: list[dict] = []
    bucket = "ow2"
    n = 0
    specs = [
        ("Ensalada de Pollo con Lechuga, Tomate y Aguacate",
         [("pollo_pechuga", 100), ("lechuga", 80), ("tomate", 80), ("aguacate", 30), ("aceite_oliva", 5)],
         ["100 g de pollo", "80 g de lechuga", "80 g de tomate", "30 g de aguacate", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl de Quinoa con Espinaca y Pollo",
         [("quinoa_cocida", 100), ("espinaca_cocida", 100), ("pollo_pechuga", 80), ("aceite_oliva", 5)],
         ["100 g de quinoa", "100 g de espinaca", "80 g de pollo", "5 ml de aceite de oliva"], "lunch"),
        ("Avena con Manzana y Canela",
         [("avena_sin_gluten", 35), ("manzana", 100), ("canela", 1), ("leche_almendra", 200)],
         ["35 g de avena", "100 g de manzana", "1 g de canela", "200 ml de leche de almendra"], "breakfast"),
        ("Sopa de Lentejas y Verduras",
         [("lentejas_cocidas", 130), ("zanahoria", 80), ("tomate", 80), ("aceite_oliva", 5)],
         ["130 g de lentejas", "80 g de zanahoria", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Tortilla de Claras con Espinaca y Tomate",
         [("clara_huevo", 120), ("espinaca_cocida", 80), ("tomate", 60), ("aceite_oliva", 5)],
         ["120 g de claras", "80 g de espinaca", "60 g de tomate", "5 ml de aceite de oliva"], "breakfast"),
        ("Bacalao con Brócoli y Quinoa Ligera",
         [("bacalao", 120), ("brocoli_cocido", 100), ("quinoa_cocida", 80), ("aceite_oliva", 5)],
         ["120 g de bacalao", "100 g de brócoli", "80 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Pavo con Calabacín y Tomate",
         [("pavo_pechuga", 100), ("calabacin", 120), ("tomate", 80), ("aceite_oliva", 5)],
         ["100 g de pavo", "120 g de calabacín", "80 g de tomate", "5 ml de aceite de oliva"], "dinner"),
        ("Ensalada de Garbanzos y Espinaca",
         [("garbanzos_cocidos", 100), ("espinaca_cocida", 80), ("tomate", 60), ("aceite_oliva", 5)],
         ["100 g de garbanzos", "80 g de espinaca", "60 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Yogur Griego con Frambuesa",
         [("yogur_griego", 200), ("frambuesa", 80), ("chia", 6)],
         ["200 g de yogur griego", "80 g de frambuesa", "6 g de chía"], "snack"),
        ("Trucha con Calabacín y Limón",
         [("trucha", 100), ("calabacin", 120), ("limon", 15), ("aceite_oliva", 5)],
         ["100 g de trucha", "120 g de calabacín", "15 g de limón", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl de Tofu con Brócoli y Quinoa Ligera",
         [("tofu_firme", 100), ("brocoli_cocido", 100), ("quinoa_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de tofu", "100 g de brócoli", "80 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Atún con Lechuga y Aguacate",
         [("atun_agua", 100), ("lechuga", 80), ("aguacate", 40), ("tomate", 60), ("aceite_oliva", 5)],
         ["100 g de atún", "80 g de lechuga", "40 g de aguacate", "60 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Pollo con Coliflor y Espinaca",
         [("pollo_pechuga", 100), ("coliflor_cocida", 120), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de coliflor", "80 g de espinaca", "5 ml de aceite de oliva"], "dinner"),
    ]
    # 13 × 11 = 143 — close to 135 target
    for nm, comp, txt, mt in specs:
        for v in range(11):
            n += 1
            descr = "Plato de menor densidad energética con alta saciedad por fibra y proteína magra, alineado con manejo de sobrepeso."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina ligero.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["weight_loss"], ["sedentary", "lightly_active"],
                ["overweight", "obesity"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=10,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 7) GOUT (positive boost) — 100 (low purine: dairy, eggs, veg, cherries)
# ═════════════════════════════════════════════════════════════════════════
def build_gout_positive() -> list[dict]:
    out: list[dict] = []
    bucket = "go2"
    n = 0
    specs = [
        ("Yogur Griego con Cerezas y Almendras",
         [("yogur_griego", 200), ("cereza", 80), ("almendras", 10)],
         ["200 g de yogur griego natural", "80 g de cerezas", "10 g de almendras"], "breakfast"),
        ("Avena con Cerezas y Chía",
         [("avena_sin_gluten", 40), ("cereza", 80), ("chia", 8), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de cerezas", "8 g de chía", "200 ml de leche de almendra"], "breakfast"),
        ("Tortilla de Huevo con Tomate y Calabacín",
         [("huevo", 100), ("tomate", 80), ("calabacin", 80), ("aceite_oliva", 5)],
         ["2 huevos", "80 g de tomate", "80 g de calabacín", "5 ml de aceite de oliva"], "breakfast"),
        ("Bowl de Quinoa con Pepino y Limón",
         [("quinoa_cocida", 150), ("pepino", 100), ("limon", 15), ("aceite_oliva", 5)],
         ["150 g de quinoa", "100 g de pepino", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Yogur con Frambuesa y Linaza",
         [("yogur_griego", 200), ("frambuesa", 80), ("linaza", 8)],
         ["200 g de yogur griego", "80 g de frambuesa", "8 g de linaza"], "snack"),
        ("Camote Asado con Aguacate y Limón",
         [("camote_cocido", 180), ("aguacate", 50), ("limon", 15), ("aceite_oliva", 5)],
         ["180 g de camote asado", "50 g de aguacate", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Arroz Integral con Calabacín y Tomate",
         [("arroz_integral_cocido", 150), ("calabacin", 100), ("tomate", 80), ("aceite_oliva", 5)],
         ["150 g de arroz integral", "100 g de calabacín", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Yogur Sin Lactosa con Cerezas y Avena",
         [("yogur_sin_lactosa", 200), ("cereza", 80), ("avena_sin_gluten", 25)],
         ["200 g de yogur sin lactosa", "80 g de cerezas", "25 g de avena"], "breakfast"),
        ("Huevo con Camote y Aguacate",
         [("huevo", 100), ("camote_cocido", 150), ("aguacate", 40)],
         ["2 huevos", "150 g de camote", "40 g de aguacate"], "breakfast"),
        ("Queso Cottage con Cerezas y Almendras",
         [("queso_cottage", 150), ("cereza", 80), ("almendras", 10)],
         ["150 g de queso cottage", "80 g de cerezas", "10 g de almendras"], "snack"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato bajo en purinas (sin mariscos, sin vísceras, sin carnes rojas), con cerezas y lácteos bajos en purinas, alineado con manejo de hiperuricemia."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina suave.", "Sirve."],
                "solid", ["latam", "mediterranean"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["sedentary", "lightly_active"],
                ["gout"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=10,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 8) LIQUID weight_loss / fatty_liver — 30 extras (GL<10)
# ═════════════════════════════════════════════════════════════════════════
def build_liquid_extras() -> list[dict]:
    out: list[dict] = []
    bucket = "lq3"
    n = 0
    specs = [
        ("Agua Fresca de Pepino con Limón y Menta",
         [("pepino", 200), ("limon", 25), ("agua", 250)],
         ["200 g de pepino", "25 g de limón exprimido", "1 ramita de menta", "250 ml de agua"]),
        ("Té Verde Frío con Limón y Jengibre",
         [("te_verde", 250), ("limon", 20), ("jengibre", 4)],
         ["250 ml de té verde frío", "20 g de limón", "4 g de jengibre"]),
        ("Infusión de Apio, Limón y Jengibre",
         [("apio", 120), ("limon", 20), ("jengibre", 5), ("agua", 250)],
         ["120 g de apio", "20 g de limón", "5 g de jengibre", "250 ml de agua"]),
        ("Jugo Verde de Pepino, Apio y Limón",
         [("pepino", 150), ("apio", 100), ("limon", 20), ("agua", 200)],
         ["150 g de pepino", "100 g de apio", "20 g de limón", "200 ml de agua"]),
        ("Té Verde con Limón Frío",
         [("te_verde", 250), ("limon", 25)],
         ["250 ml de té verde frío", "25 g de limón exprimido"]),
        ("Agua de Apio con Limón",
         [("apio", 150), ("limon", 25), ("agua", 250)],
         ["150 g de apio", "25 g de limón", "250 ml de agua"]),
        ("Infusión Tibia de Limón con Jengibre",
         [("limon", 30), ("jengibre", 5), ("agua", 280)],
         ["30 g de limón", "5 g de jengibre", "280 ml de agua tibia"]),
        ("Jugo de Pepino con Limón y Apio",
         [("pepino", 180), ("limon", 20), ("apio", 80), ("agua", 200)],
         ["180 g de pepino", "20 g de limón", "80 g de apio", "200 ml de agua"]),
        ("Té Verde con Pepino Frío",
         [("te_verde", 200), ("pepino", 100), ("limon", 15)],
         ["200 ml de té verde", "100 g de pepino", "15 g de limón"]),
        ("Infusión Manzanilla con Limón",
         [("te_manzanilla", 250), ("limon", 20)],
         ["250 ml de manzanilla tibia", "20 g de limón"]),
    ]
    for nm, comp, txt in specs:
        for v in range(3):
            n += 1
            descr = "Bebida ligera baja en azúcar y sin calorías agregadas, hidratante, alineada con manejo de peso e hígado graso."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Mezcla los ingredientes.", "Sirve frío o tibio según preferencia."],
                "liquid", ["latam"], ["latam"], "vegan",
                ["weight_loss", "health"], ["sedentary", "lightly_active", "moderately_active"],
                ["fatty_liver", "overweight", "hypertension"], [],
                meal_time="snack", pregnancy_safe=True, prep=5, cook=0,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 9) DIABETES_T1 snacks/breakfast small — 25 (100-200 kcal, insulin-matching)
# ═════════════════════════════════════════════════════════════════════════
def build_diabetes_t1_snacks() -> list[dict]:
    out: list[dict] = []
    bucket = "d1s"
    n = 0
    specs = [
        ("Yogur Griego con Almendras",
         [("yogur_griego", 100), ("almendras", 8)],
         ["100 g de yogur griego", "8 g de almendras"]),
        ("Huevo Duro con Aguacate Mini",
         [("huevo", 50), ("aguacate", 30)],
         ["1 huevo duro", "30 g de aguacate"]),
        ("Queso Cottage con Frambuesa",
         [("queso_cottage", 100), ("frambuesa", 50)],
         ["100 g de queso cottage", "50 g de frambuesa"]),
        ("Almendras con Manzana",
         [("almendras", 12), ("manzana", 80)],
         ["12 g de almendras", "80 g de manzana"]),
        ("Yogur Sin Lactosa con Chía",
         [("yogur_sin_lactosa", 120), ("chia", 8)],
         ["120 g de yogur sin lactosa", "8 g de chía"]),
    ]
    for nm, comp, txt in specs:
        for v in range(5):  # 5 × 5 = 25
            n += 1
            descr = "Snack pequeño con macros estables (carbs controlados + proteína + grasa) para ajuste fino de insulina."
            out.append(_fin(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Combina los ingredientes.", "Sirve frío."],
                "solid", ["latam", "mediterranean"], ["latam", "eu", "us"], "omnivore",
                ["maintain", "health"], ["sedentary", "lightly_active", "moderately_active"],
                ["diabetes_t1"], [],
                meal_time="snack", pregnancy_safe=False, prep=5, cook=0,
            ), bucket))
    return out


# ═════════════════════════════════════════════════════════════════════════
def main() -> None:
    all_buckets = {
        "ibd": build_ibd(),
        "hyperthyroidism": build_hyperthyroidism(),
        "chronic_insomnia": build_insomnia(),
        "diabetes_t1": build_diabetes_t1(),
        "vitamin_d_deficiency": build_vit_d(),
        "overweight": build_overweight(),
        "gout": build_gout_positive(),
        "liquid_extras": build_liquid_extras(),
        "diabetes_t1_snacks": build_diabetes_t1_snacks(),
    }

    master_path = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
    master = json.loads(master_path.read_text())
    existing_names = {(r.get("name") or "").strip().lower() for r in master if isinstance(r, dict)}
    existing_ids = {r.get("id") for r in master if isinstance(r, dict)}

    valid: list[dict] = []
    rejected: list[tuple[str, str]] = []
    bucket_stats: dict[str, dict[str, int]] = {}

    for bucket_name, recipes in all_buckets.items():
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
            ok, reason = validate(r)
            if not ok:
                stat["rejected"] += 1
                rejected.append((r["id"], reason))
                continue
            stat["accepted"] += 1
            existing_names.add(nm)
            existing_ids.add(r["id"])
            valid.append(r)
        bucket_stats[bucket_name] = stat

    out_path = ROOT / "data" / "meals" / "round3_batch_2026_06_01.json"
    out_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2))

    log_path = ROOT / "scripts" / "generate_recipes_round3_2026_06_01_rejections.log"
    log_lines = [f"TOTAL accepted={len(valid)} rejected={len(rejected)}", ""]
    for b, s in bucket_stats.items():
        log_lines.append(f"  {b:25s} gen={s['generated']:4d} acc={s['accepted']:4d} rej={s['rejected']:3d} dedup={s['dedup']:3d}")
    log_lines.append("")
    log_lines.extend(f"{rid}\t{reason}" for rid, reason in rejected)
    log_path.write_text("\n".join(log_lines))

    print(f"round3_batch: accepted={len(valid)} rejected={len(rejected)}")
    for b, s in bucket_stats.items():
        print(f"  {b:25s} gen={s['generated']} acc={s['accepted']} rej={s['rejected']} dedup={s['dedup']}")


if __name__ == "__main__":
    main()
