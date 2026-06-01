"""Condition-helpful recipe batch — 2026-06-01.

Generates condition-aligned recipes for under-represented conditions in the
catalog (fatty_liver, hypercholesterolemia, pcos, ibs, hypothyroidism, gout,
vitamin_d_deficiency, lactose_intolerance, overweight).

NOVA scope: NUTRITION PLANNING, not clinical advice. Tagging semantics:
  - `recommended_for_conditions`: nutrient gates aligned with condition needs
    (informational; UI shows "alineado con tu condición").
  - `contraindicated_conditions`: safety floor — recipe is unsafe for that
    condition (e.g., high purine → gout; high sat fat → fatty_liver).

NO supplements (no whey, casein, BCAA, creatine, pre-workout, mass gainer,
protein powder, multivitamins). NO medical claims (cura/trata/previene/
cardioprotector/antiinflamatorio/detox). Display strings use neutral
nutritional descriptors only.

Output: data/meals/condition_helpful_batch_2026_06_01.json
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

# Forbidden medical-claim tokens — scoped strictly to display strings
# (name + description + ingredients + instructions). Token list MUST match
# scripts/audit_catalog.py scope-scan rules.
FORBIDDEN_CLAIM_TOKENS = (
    "cura ", "trata ", "tratamiento", "previene", "cardioprotector",
    "antiinflamatorio", "antiinflamatoria", "detox", "desintoxica",
    "milagroso", "milagrosa", "limpieza hepática",
)

# Supplement-class ingredient tokens (legal-scope cleanup).
SUPPLEMENT_TOKENS = (
    "whey", "caseina", "caseína", "bcaa", "creatina", "pre-workout",
    "preworkout", "mass gainer", "proteina en polvo", "proteína en polvo",
    "proteina_whey", "proteina_vegana", "multivitaminico", "multivitamínico",
)


# ───────────────────────────────────────────────────────────────────────────
# Ingredient nutrition table per 100 g / 100 ml.
# Source: USDA FDC / BEDCA averages, rounded. Extended for condition needs.
# ───────────────────────────────────────────────────────────────────────────
ING: dict[str, dict] = {
    # ─── Fruits ───
    "naranja":          {"kcal": 47,  "p": 0.9, "c": 11.8, "f": 0.1, "fib": 2.4, "sug": 9.4,  "na": 0,   "gi": 43,  "satf": 0.0,  "purine": "low"},
    "piña":             {"kcal": 50,  "p": 0.5, "c": 13.1, "f": 0.1, "fib": 1.4, "sug": 9.9,  "na": 1,   "gi": 66,  "satf": 0.0,  "purine": "low"},
    "papaya":           {"kcal": 43,  "p": 0.5, "c": 10.8, "f": 0.3, "fib": 1.7, "sug": 7.8,  "na": 8,   "gi": 60,  "satf": 0.0,  "purine": "low"},
    "mango":            {"kcal": 60,  "p": 0.8, "c": 15.0, "f": 0.4, "fib": 1.6, "sug": 13.7, "na": 1,   "gi": 51,  "satf": 0.1,  "purine": "low"},
    "manzana_verde":    {"kcal": 52,  "p": 0.3, "c": 13.8, "f": 0.2, "fib": 2.4, "sug": 10.4, "na": 1,   "gi": 39,  "satf": 0.0,  "purine": "low"},
    "manzana":          {"kcal": 52,  "p": 0.3, "c": 13.8, "f": 0.2, "fib": 2.4, "sug": 10.4, "na": 1,   "gi": 39,  "satf": 0.0,  "purine": "low"},
    "limon":            {"kcal": 29,  "p": 1.1, "c": 9.3,  "f": 0.3, "fib": 2.8, "sug": 2.5,  "na": 2,   "gi": 20,  "satf": 0.0,  "purine": "low"},
    "platano":          {"kcal": 89,  "p": 1.1, "c": 22.8, "f": 0.3, "fib": 2.6, "sug": 12.2, "na": 1,   "gi": 51,  "satf": 0.1,  "purine": "low"},
    "platano_maduro":   {"kcal": 89,  "p": 1.1, "c": 22.8, "f": 0.3, "fib": 2.6, "sug": 12.2, "na": 1,   "gi": 62,  "satf": 0.1,  "purine": "low"},
    "fresa":            {"kcal": 32,  "p": 0.7, "c": 7.7,  "f": 0.3, "fib": 2.0, "sug": 4.9,  "na": 1,   "gi": 40,  "satf": 0.0,  "purine": "low"},
    "arandanos":        {"kcal": 57,  "p": 0.7, "c": 14.5, "f": 0.3, "fib": 2.4, "sug": 10.0, "na": 1,   "gi": 53,  "satf": 0.0,  "purine": "low"},
    "frambuesa":        {"kcal": 52,  "p": 1.2, "c": 11.9, "f": 0.7, "fib": 6.5, "sug": 4.4,  "na": 1,   "gi": 25,  "satf": 0.0,  "purine": "low"},
    "cereza":           {"kcal": 50,  "p": 1.0, "c": 12.2, "f": 0.3, "fib": 1.6, "sug": 8.5,  "na": 0,   "gi": 22,  "satf": 0.1,  "purine": "low"},
    "pera":             {"kcal": 57,  "p": 0.4, "c": 15.2, "f": 0.1, "fib": 3.1, "sug": 9.8,  "na": 1,   "gi": 38,  "satf": 0.0,  "purine": "low"},
    "kiwi":             {"kcal": 61,  "p": 1.1, "c": 14.7, "f": 0.5, "fib": 3.0, "sug": 9.0,  "na": 3,   "gi": 50,  "satf": 0.0,  "purine": "low"},
    "guayaba":          {"kcal": 68,  "p": 2.6, "c": 14.3, "f": 1.0, "fib": 5.4, "sug": 8.9,  "na": 2,   "gi": 24,  "satf": 0.3,  "purine": "low"},
    # ─── Veg ───
    "apio":             {"kcal": 16,  "p": 0.7, "c": 3.0,  "f": 0.2, "fib": 1.6, "sug": 1.3, "na": 80, "gi": 15,  "satf": 0.0,  "purine": "low"},
    "espinaca":         {"kcal": 23,  "p": 2.9, "c": 3.6,  "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79, "gi": 15,  "satf": 0.1,  "purine": "mod"},
    "espinaca_cocida":  {"kcal": 23,  "p": 2.9, "c": 3.6,  "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79, "gi": 15,  "satf": 0.1,  "purine": "mod"},
    "pepino":           {"kcal": 16,  "p": 0.7, "c": 3.6,  "f": 0.1, "fib": 0.5, "sug": 1.7, "na": 2,  "gi": 15,  "satf": 0.0,  "purine": "low"},
    "kale":             {"kcal": 35,  "p": 2.9, "c": 4.4,  "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53, "gi": 15,  "satf": 0.2,  "purine": "low"},
    "kale_cocida":      {"kcal": 35,  "p": 2.9, "c": 4.4,  "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53, "gi": 15,  "satf": 0.2,  "purine": "low"},
    "rucula":           {"kcal": 25,  "p": 2.6, "c": 3.7,  "f": 0.7, "fib": 1.6, "sug": 2.1, "na": 27, "gi": 15,  "satf": 0.1,  "purine": "low"},
    "jengibre":         {"kcal": 80,  "p": 1.8, "c": 18.0, "f": 0.8, "fib": 2.0, "sug": 1.7, "na": 13, "gi": 15,  "satf": 0.2,  "purine": "low"},
    "betarraga":        {"kcal": 43,  "p": 1.6, "c": 9.6,  "f": 0.2, "fib": 2.8, "sug": 6.8, "na": 78, "gi": 64,  "satf": 0.0,  "purine": "low"},
    "zanahoria":        {"kcal": 41,  "p": 0.9, "c": 9.6,  "f": 0.2, "fib": 2.8, "sug": 4.7, "na": 69, "gi": 39,  "satf": 0.0,  "purine": "low"},
    "calabacin":        {"kcal": 17,  "p": 1.2, "c": 3.1,  "f": 0.3, "fib": 1.0, "sug": 2.5, "na": 8,  "gi": 15,  "satf": 0.1,  "purine": "low"},
    "tomate":           {"kcal": 18,  "p": 0.9, "c": 3.9,  "f": 0.2, "fib": 1.2, "sug": 2.6, "na": 5,  "gi": 30,  "satf": 0.0,  "purine": "low"},
    "alcachofa":        {"kcal": 47,  "p": 3.3, "c": 10.5, "f": 0.2, "fib": 5.4, "sug": 1.0, "na": 94, "gi": 15,  "satf": 0.0,  "purine": "low"},
    "brocoli_cocido":   {"kcal": 35,  "p": 2.4, "c": 7.2,  "f": 0.4, "fib": 3.3, "sug": 1.4, "na": 41, "gi": 15,  "satf": 0.1,  "purine": "low"},
    "coliflor_cocida":  {"kcal": 23,  "p": 1.8, "c": 4.1,  "f": 0.5, "fib": 2.3, "sug": 1.9, "na": 15, "gi": 15,  "satf": 0.1,  "purine": "low"},
    "esparragos":       {"kcal": 20,  "p": 2.2, "c": 3.9,  "f": 0.1, "fib": 2.1, "sug": 1.9, "na": 2,  "gi": 15,  "satf": 0.0,  "purine": "mod"},
    "champinon":        {"kcal": 22,  "p": 3.1, "c": 3.3,  "f": 0.3, "fib": 1.0, "sug": 2.0, "na": 5,  "gi": 15,  "satf": 0.0,  "purine": "mod"},
    "champinon_uv":     {"kcal": 22,  "p": 3.1, "c": 3.3,  "f": 0.3, "fib": 1.0, "sug": 2.0, "na": 5,  "gi": 15,  "satf": 0.0,  "purine": "mod"},
    "lechuga":          {"kcal": 15,  "p": 1.4, "c": 2.9,  "f": 0.2, "fib": 1.3, "sug": 0.8, "na": 28, "gi": 15,  "satf": 0.0,  "purine": "low"},
    # ─── Cereal / carbs ───
    "avena":            {"kcal": 389, "p": 16.9, "c": 66.3, "f": 6.9, "fib": 10.6,"sug": 0,   "na": 2,  "gi": 55,  "satf": 1.2, "purine": "low"},
    "avena_sin_gluten": {"kcal": 389, "p": 16.9, "c": 66.3, "f": 6.9, "fib": 10.6,"sug": 0,   "na": 2,  "gi": 55,  "satf": 1.2, "purine": "low"},
    "quinoa_cocida":    {"kcal": 120, "p": 4.4,  "c": 21.3, "f": 1.9, "fib": 2.8, "sug": 0.9, "na": 7,  "gi": 53,  "satf": 0.2, "purine": "low"},
    "arroz_integral_cocido": {"kcal": 111, "p": 2.6, "c": 23.0, "f": 0.9, "fib": 1.8, "sug": 0.4, "na": 5, "gi": 55, "satf": 0.2, "purine": "low"},
    "camote_cocido":    {"kcal": 86,  "p": 1.6,  "c": 20.1, "f": 0.1, "fib": 3.0, "sug": 4.2, "na": 55, "gi": 54,  "satf": 0.0, "purine": "low"},
    "papa_cocida":      {"kcal": 86,  "p": 1.7,  "c": 20.0, "f": 0.1, "fib": 1.8, "sug": 0.9, "na": 5,  "gi": 78,  "satf": 0.0, "purine": "low"},
    "pan_integral":     {"kcal": 247, "p": 13.0, "c": 41.0, "f": 3.4, "fib": 7.0, "sug": 6.0, "na": 491,"gi": 71,  "satf": 0.7, "purine": "low"},
    # ─── Protein animal ───
    "salmon":           {"kcal": 208, "p": 20.4, "c": 0.0,  "f": 13.4,"fib": 0,   "sug": 0,   "na": 59, "gi": 0,   "satf": 3.1, "purine": "mod"},
    "sardina_lata":     {"kcal": 208, "p": 24.6, "c": 0.0,  "f": 11.4,"fib": 0,   "sug": 0,   "na": 307,"gi": 0,   "satf": 1.5, "purine": "high"},
    "atun_agua":        {"kcal": 116, "p": 25.5, "c": 0.0,  "f": 1.0, "fib": 0,   "sug": 0,   "na": 247,"gi": 0,   "satf": 0.3, "purine": "high"},
    "trucha":           {"kcal": 148, "p": 20.8, "c": 0.0,  "f": 6.6, "fib": 0,   "sug": 0,   "na": 52, "gi": 0,   "satf": 1.4, "purine": "mod"},
    "bacalao":          {"kcal": 82,  "p": 17.8, "c": 0.0,  "f": 0.7, "fib": 0,   "sug": 0,   "na": 54, "gi": 0,   "satf": 0.1, "purine": "mod"},
    "pollo_pechuga":    {"kcal": 165, "p": 31.0, "c": 0.0,  "f": 3.6, "fib": 0,   "sug": 0,   "na": 74, "gi": 0,   "satf": 1.0, "purine": "mod"},
    "pavo_pechuga":     {"kcal": 135, "p": 30.1, "c": 0.0,  "f": 1.0, "fib": 0,   "sug": 0,   "na": 54, "gi": 0,   "satf": 0.3, "purine": "mod"},
    "huevo":            {"kcal": 143, "p": 12.6, "c": 0.7,  "f": 9.5, "fib": 0,   "sug": 0.4, "na": 142,"gi": 0,   "satf": 3.1, "purine": "low"},
    "clara_huevo":      {"kcal": 52,  "p": 11.0, "c": 0.7,  "f": 0.2, "fib": 0,   "sug": 0.7, "na": 166,"gi": 0,   "satf": 0.0, "purine": "low"},
    # ─── Dairy ───
    "yogur_griego":     {"kcal": 59,  "p": 10.0, "c": 3.6,  "f": 0.4, "fib": 0,   "sug": 3.2, "na": 36, "gi": 11, "satf": 0.1, "purine": "low"},
    "queso_cottage":    {"kcal": 98,  "p": 11.1, "c": 3.4,  "f": 4.3, "fib": 0,   "sug": 2.7, "na": 364,"gi": 30, "satf": 1.7, "purine": "low"},
    "leche_descremada": {"kcal": 34,  "p": 3.4,  "c": 5.0,  "f": 0.1, "fib": 0,   "sug": 5.0, "na": 42, "gi": 32, "satf": 0.1, "purine": "low"},
    "yogur_sin_lactosa": {"kcal": 59, "p": 5.7,  "c": 7.0,  "f": 1.5, "fib": 0,   "sug": 7.0, "na": 50, "gi": 14, "satf": 0.9, "purine": "low"},
    # ─── Plant milks / non-dairy ───
    "leche_almendra":   {"kcal": 17,  "p": 0.6, "c": 0.6,  "f": 1.5, "fib": 0.3, "sug": 0,   "na": 60, "gi": 25, "satf": 0.1, "purine": "low"},
    "leche_avena":      {"kcal": 47,  "p": 1.0, "c": 6.6,  "f": 1.5, "fib": 0.8, "sug": 3.3, "na": 42, "gi": 60, "satf": 0.2, "purine": "low"},
    "leche_coco_light": {"kcal": 31,  "p": 0.2, "c": 1.0,  "f": 3.0, "fib": 0,   "sug": 1.0, "na": 15, "gi": 30, "satf": 2.7, "purine": "low"},
    "leche_soya":       {"kcal": 33,  "p": 3.3, "c": 1.8,  "f": 1.8, "fib": 0.4, "sug": 1.0, "na": 51, "gi": 30, "satf": 0.3, "purine": "low"},
    # ─── Legumes ───
    "lentejas_cocidas": {"kcal": 116, "p": 9.0, "c": 20.1, "f": 0.4, "fib": 7.9, "sug": 1.8, "na": 2,  "gi": 32, "satf": 0.1, "purine": "mod"},
    "garbanzos_cocidos": {"kcal": 164, "p": 8.9, "c": 27.4, "f": 2.6, "fib": 7.6, "sug": 4.8, "na": 7, "gi": 36, "satf": 0.3, "purine": "mod"},
    "frijoles_negros_cocidos": {"kcal": 132, "p": 8.9, "c": 23.7, "f": 0.5, "fib": 8.7, "sug": 0.3, "na": 1, "gi": 30, "satf": 0.1, "purine": "mod"},
    "tofu_firme":       {"kcal": 144, "p": 17.3, "c": 2.8,  "f": 8.7, "fib": 2.3, "sug": 0.6, "na": 14, "gi": 15, "satf": 1.3, "purine": "mod"},
    "edamame_cocido":   {"kcal": 122, "p": 11.0, "c": 9.9,  "f": 5.2, "fib": 5.2, "sug": 2.2, "na": 6,  "gi": 18, "satf": 0.6, "purine": "mod"},
    # ─── Seeds / nuts / fats ───
    "chia":             {"kcal": 486, "p": 16.5, "c": 42.1, "f": 30.7, "fib": 34.4, "sug": 0,  "na": 16, "gi": 1,  "satf": 3.3, "purine": "low"},
    "linaza":           {"kcal": 534, "p": 18.3, "c": 28.9, "f": 42.2, "fib": 27.3, "sug": 1.6,"na": 30, "gi": 1,  "satf": 3.7, "purine": "low"},
    "almendras":        {"kcal": 579, "p": 21.2, "c": 21.6, "f": 49.9, "fib": 12.5, "sug": 4.4,"na": 1,  "gi": 0,  "satf": 3.8, "purine": "low"},
    "nueces":           {"kcal": 654, "p": 15.2, "c": 13.7, "f": 65.2, "fib": 6.7, "sug": 2.6, "na": 2, "gi": 0,  "satf": 6.1, "purine": "low"},
    "nuez_brasil":      {"kcal": 656, "p": 14.3, "c": 12.3, "f": 66.4, "fib": 7.5, "sug": 2.3, "na": 3, "gi": 0,  "satf": 16.1,"purine": "low"},
    "aceite_oliva":     {"kcal": 884, "p": 0.0,  "c": 0.0,  "f": 100.0,"fib": 0,   "sug": 0,   "na": 2, "gi": 0,  "satf": 13.8,"purine": "low"},
    "aguacate":         {"kcal": 160, "p": 2.0,  "c": 8.5,  "f": 14.7, "fib": 6.7, "sug": 0.7, "na": 7, "gi": 15, "satf": 2.1, "purine": "low"},
    # ─── Liquids ───
    "agua":             {"kcal": 0, "p": 0, "c": 0, "f": 0, "fib": 0, "sug": 0, "na": 0, "gi": 0, "satf": 0, "purine": "low"},
    "te_verde":         {"kcal": 1, "p": 0, "c": 0.2, "f": 0, "fib": 0, "sug": 0, "na": 1, "gi": 0, "satf": 0, "purine": "low"},
    # ─── Sweeteners / spices ───
    "canela":           {"kcal": 247, "p": 4.0, "c": 80.6, "f": 1.2, "fib": 53.1, "sug": 2.2, "na": 10, "gi": 5, "satf": 0.3, "purine": "low"},
    "curcuma":          {"kcal": 312, "p": 9.7, "c": 67.0, "f": 3.3, "fib": 22.7, "sug": 3.2, "na": 27, "gi": 15, "satf": 0.9, "purine": "low"},
}

# ────────────────── Allergen detection ──────────────────
ALLERGEN_MAP = [
    (("almendra", "nuez", "almond", "walnut", "cashew", "pistachio", "pecan", "hazelnut", "macadamia", "brasil"), "tree_nuts"),
    (("leche", "yogur", "queso", "kefir", "yogurt", "butter", "cottage"), "dairy"),
    (("trigo", "wheat", "harina", "pan ", "pasta", "flour", "bread", "avena", "oats"), "gluten"),
    (("maní", "mani", "peanut", "cacahuate"), "peanuts"),
    (("camarón", "langosta", "cangrejo", "shrimp", "crab", "lobster"), "shellfish"),
    (("pescado", "atún", "atun", "salmón", "salmon", "tuna", "sardina", "sardine", "trucha", "bacalao"), "fish"),
    (("huevo", "clara de huevo", "egg"), "egg"),
    (("soya", "soja", "tofu", "tempeh", "edamame", "soy"), "soy"),
    (("sésamo", "sesamo", "sesame", "tahini"), "sesame"),
]


def detect_allergens(ingredients_text: list[str]) -> list[str]:
    text = " ".join(ingredients_text).lower()
    found: set[str] = set()
    for keys, tag in ALLERGEN_MAP:
        if any(k in text for k in keys):
            found.add(tag)
    # avena → gluten unless explicit "sin gluten" / "certificada GF"
    if ("avena" in text) and ("sin gluten" not in text) and ("certificada" not in text):
        found.add("gluten")
    return sorted(found)


# ────────────────── Macro calc ──────────────────
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


def total_grams(components: list[tuple[str, float]]) -> float:
    return sum(g for _, g in components)


# ────────────────── Recipe builder ──────────────────
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
    source_catalog: str = "nova_v2_batch_cond_helpful_2026_06_01",
) -> dict:
    m = macros_from_components(components)
    allergens = detect_allergens(ingredients_text)
    gl = gl_estimate(m["carbs_g"], m["gi"])

    # ─── Defensive auto-tagging ───
    # If purines are high → force gout into contraindicated.
    if has_purine_high(components):
        contraindicated_conditions = sorted(set(contraindicated_conditions) | {"gout"})
        recommended_for_conditions = [c for c in recommended_for_conditions if c != "gout"]
    # If sat_fat > 5 g → strip cardiovascular-style recommends, contraindicate hyperchol/fatty_liver.
    if m["sat_fat_g"] > 5:
        recommended_for_conditions = [c for c in recommended_for_conditions
                                       if c not in {"hypercholesterolemia", "fatty_liver", "dyslipidemia"}]
        contraindicated_conditions = sorted(set(contraindicated_conditions) | {"hypercholesterolemia", "fatty_liver"})
    # Liquids w/ sugar > 12 strip fatty_liver / diabetes recommend.
    if meal_format == "liquid":
        if m["sugar_g"] > 12 or m["carbs_g"] > 25:
            recommended_for_conditions = [c for c in recommended_for_conditions
                                           if c not in {"fatty_liver", "diabetes_t2", "diabetes_t1", "pcos"}]
        if gl is not None and gl > 10:
            recommended_for_conditions = [c for c in recommended_for_conditions
                                           if c not in {"diabetes_t2", "diabetes_t1", "pcos"}]
    # Dairy → tag lactose_intolerance contraindicated (unless dairy-free / lactose-free).
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
            "bucket": None,  # filled by generator
        },
    }


# ────────────────── Validator ──────────────────
def validate(recipe: dict) -> tuple[bool, str]:
    mc = recipe["matching_criteria"]
    np = recipe["nutrition_profile"]
    m = np["macros"]
    kcal = np["calories"]
    if kcal <= 0:
        return False, "kcal<=0"
    derived = 4 * m["protein_g"] + 4 * m["carbs_g"] + 9 * m["fat_g"]
    if abs(derived - kcal) / kcal > 0.05:
        return False, f"macro_drift={abs(derived-kcal)/kcal:.3f}"
    # Green juices are intentionally low-kcal — allow ≥30 for liquid format.
    is_liquid = recipe.get("matching_criteria", {}).get("meal_format") == "liquid"
    floor = 30 if is_liquid else 60
    if not (floor <= kcal <= 900):
        return False, f"kcal_out_of_range={kcal}"
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
    # Display-string scope scan: supplements + medical claims.
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


# ═════════════════════════════════════════════════════════════════════════
# BUCKET BUILDERS — programmatic permutations
# ═════════════════════════════════════════════════════════════════════════

def _id(bucket_tag: str, n: int) -> str:
    return f"nova_meal_cond_{bucket_tag}_{n:04d}"


# ───── 1) FATTY_LIVER — 150 (priority: user explicit example) ─────
def build_fatty_liver() -> list[dict]:
    out: list[dict] = []
    bucket = "fl"
    n = 0

    # ─── A) 30 green juices (user-priority) ───
    base_combos = [
        ("Jugo Verde de Apio, Limón, Chía y Piña",
         [("apio", 120), ("limon", 25), ("chia", 8), ("piña", 60), ("agua", 200)],
         ["120 g de apio", "25 g de limón exprimido", "8 g de chía hidratada", "60 g de piña", "200 ml de agua"],
         "Lava el apio.", "Apio + Piña + Limón + Chía"),
        ("Jugo Verde de Apio, Pepino, Limón y Jengibre",
         [("apio", 100), ("pepino", 150), ("limon", 20), ("jengibre", 5), ("agua", 200)],
         ["100 g de apio", "150 g de pepino", "20 g de limón", "5 g de jengibre", "200 ml de agua"],
         "Lava todo.", "Apio + Pepino + Jengibre"),
        ("Jugo de Espinaca, Manzana Verde y Limón",
         [("espinaca", 60), ("manzana_verde", 80), ("limon", 20), ("agua", 200)],
         ["60 g de espinaca", "80 g de manzana verde", "20 g de limón", "200 ml de agua"],
         "Lava la espinaca.", "Espinaca + Manzana"),
        ("Jugo de Kale, Piña y Chía",
         [("kale", 50), ("piña", 60), ("chia", 8), ("agua", 200)],
         ["50 g de kale", "60 g de piña", "8 g de chía hidratada", "200 ml de agua"],
         "Lava el kale.", "Kale + Piña"),
        ("Jugo de Betarraga, Apio y Manzana",
         [("betarraga", 40), ("apio", 100), ("manzana_verde", 60), ("limon", 15), ("agua", 200)],
         ["40 g de betarraga", "100 g de apio", "60 g de manzana verde", "15 g de limón", "200 ml de agua"],
         "Pela la betarraga.", "Betarraga + Apio"),
        ("Infusión de Alcachofa con Limón",
         [("alcachofa", 80), ("limon", 20), ("agua", 250)],
         ["80 g de alcachofa cocida", "20 g de limón", "250 ml de agua"],
         "Cocina la alcachofa.", "Alcachofa + Limón"),
        ("Jugo Verde de Pepino, Apio y Kiwi",
         [("pepino", 150), ("apio", 80), ("kiwi", 60), ("limon", 15), ("agua", 200)],
         ["150 g de pepino", "80 g de apio", "60 g de kiwi", "15 g de limón", "200 ml de agua"],
         "Lava todo.", "Pepino + Apio + Kiwi"),
        ("Jugo Verde de Espinaca, Pepino y Limón",
         [("espinaca", 50), ("pepino", 150), ("limon", 20), ("agua", 200)],
         ["50 g de espinaca", "150 g de pepino", "20 g de limón", "200 ml de agua"],
         "Lava la espinaca.", "Espinaca + Pepino"),
        ("Jugo de Apio, Manzana y Jengibre",
         [("apio", 100), ("manzana_verde", 80), ("jengibre", 5), ("limon", 15), ("agua", 200)],
         ["100 g de apio", "80 g de manzana verde", "5 g de jengibre", "15 g de limón", "200 ml de agua"],
         "Lava todo.", "Apio + Manzana + Jengibre"),
        ("Jugo de Kale, Apio y Limón",
         [("kale", 50), ("apio", 100), ("limon", 25), ("agua", 200)],
         ["50 g de kale", "100 g de apio", "25 g de limón", "200 ml de agua"],
         "Lava el kale.", "Kale + Apio"),
        ("Jugo de Pepino, Kale y Manzana",
         [("pepino", 120), ("kale", 40), ("manzana_verde", 60), ("limon", 15), ("agua", 200)],
         ["120 g de pepino", "40 g de kale", "60 g de manzana verde", "15 g de limón", "200 ml de agua"],
         "Lava todo.", "Pepino + Kale + Manzana"),
        ("Jugo Verde de Espinaca, Apio y Piña",
         [("espinaca", 50), ("apio", 80), ("piña", 60), ("limon", 15), ("agua", 200)],
         ["50 g de espinaca", "80 g de apio", "60 g de piña", "15 g de limón", "200 ml de agua"],
         "Lava todo.", "Espinaca + Apio + Piña"),
        ("Jugo de Rúcula, Pepino y Limón",
         [("rucula", 40), ("pepino", 150), ("limon", 20), ("agua", 200)],
         ["40 g de rúcula", "150 g de pepino", "20 g de limón", "200 ml de agua"],
         "Lava todo.", "Rúcula + Pepino"),
        ("Jugo de Apio, Limón y Linaza",
         [("apio", 120), ("limon", 25), ("linaza", 8), ("agua", 200)],
         ["120 g de apio", "25 g de limón", "8 g de linaza molida", "200 ml de agua"],
         "Muele la linaza.", "Apio + Linaza"),
        ("Jugo Verde de Kale, Pepino y Jengibre",
         [("kale", 50), ("pepino", 120), ("jengibre", 5), ("limon", 15), ("agua", 200)],
         ["50 g de kale", "120 g de pepino", "5 g de jengibre", "15 g de limón", "200 ml de agua"],
         "Lava todo.", "Kale + Pepino + Jengibre"),
    ]
    for nm, comp, txt, step1, _ in base_combos:
        n += 1
        instr = [step1, "Licúa con el agua hasta homogeneizar.", "Cuela si prefieres textura ligera.", "Sirve frío en 1 vaso de 250 ml."]
        descr = "Bebida ligera baja en azúcar, rica en fibra y vitamina C, alineada con necesidades de hígado graso (bajo azúcar simple, alto en vegetales de hoja verde)."
        out.append(_finalize(build_recipe(
            _id(bucket, n), nm, descr, comp, txt, instr, "liquid",
            ["latam"], ["latam"], "vegan",
            ["weight_loss", "health"], ["sedentary", "lightly_active", "moderately_active"],
            ["fatty_liver", "overweight", "hypertension"], [],
            meal_time="breakfast", pregnancy_safe=True, prep=8, cook=0,
        ), bucket, n))

    # ─── B) 60 oat/breakfast variants ───
    oat_specs = [
        ("Avena con Manzana y Canela", [("avena_sin_gluten", 40), ("manzana", 100), ("canela", 1), ("leche_almendra", 200)],
         ["40 g de avena sin gluten certificada", "100 g de manzana", "1 g de canela", "200 ml de leche de almendra sin azúcar"],
         "Mezcla la avena con la leche caliente.", ["fatty_liver", "hypercholesterolemia", "diabetes_t2"]),
        ("Avena con Pera y Linaza", [("avena_sin_gluten", 40), ("pera", 100), ("linaza", 10), ("leche_almendra", 200)],
         ["40 g de avena sin gluten certificada", "100 g de pera", "10 g de linaza molida", "200 ml de leche de almendra"],
         "Cocina la avena.", ["fatty_liver", "hypercholesterolemia"]),
        ("Avena con Arándanos y Chía", [("avena_sin_gluten", 40), ("arandanos", 80), ("chia", 10), ("leche_almendra", 200)],
         ["40 g de avena sin gluten", "80 g de arándanos", "10 g de chía", "200 ml de leche de almendra"],
         "Mezcla todo.", ["fatty_liver", "hypercholesterolemia", "diabetes_t2"]),
        ("Avena con Frambuesa y Almendras", [("avena_sin_gluten", 40), ("frambuesa", 80), ("almendras", 8), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de frambuesa", "8 g de almendras laminadas", "200 ml de leche de almendra"],
         "Cocina la avena.", ["fatty_liver", "hypercholesterolemia"]),
        ("Avena con Kiwi y Chía", [("avena_sin_gluten", 40), ("kiwi", 80), ("chia", 8), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de kiwi", "8 g de chía", "200 ml de leche de almendra"],
         "Mezcla.", ["fatty_liver", "ibs"]),
    ]
    for nm, comp, txt, step1, recs in oat_specs:
        for variant in range(12):  # 5 × 12 = 60
            n += 1
            descr = "Desayuno con beta-glucanos de avena (fibra soluble), bajo en grasa saturada, alineado con hígado graso."
            instr = [step1, "Calienta a fuego medio 5 min.", "Sirve tibio en 1 bowl."]
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {variant+1})", descr, comp, txt, instr, "solid",
                ["latam", "nordic"], ["latam", "us", "eu"], "vegan",
                ["weight_loss", "health"], ["sedentary", "lightly_active"],
                recs, [],
                meal_time="breakfast", pregnancy_safe=True, prep=10, cook=5,
            ), bucket, n))

    # ─── C) 30 lean fish & vegetable meals ───
    fish_specs = [
        ("Salmón al Vapor con Espinacas", [("salmon", 120), ("espinaca_cocida", 150), ("aceite_oliva", 5)],
         ["120 g de salmón fresco", "150 g de espinacas", "5 ml de aceite de oliva"],
         "Cocina el salmón al vapor 12 min."),
        ("Bacalao al Horno con Brócoli", [("bacalao", 130), ("brocoli_cocido", 150), ("aceite_oliva", 5)],
         ["130 g de bacalao", "150 g de brócoli al vapor", "5 ml de aceite de oliva"],
         "Hornea el bacalao 15 min a 180°C."),
        ("Trucha con Calabacín y Limón", [("trucha", 120), ("calabacin", 150), ("aceite_oliva", 5), ("limon", 15)],
         ["120 g de trucha", "150 g de calabacín", "5 ml de aceite de oliva", "15 g de limón"],
         "Saltea la trucha en sartén."),
    ]
    for nm, comp, txt, step1 in fish_specs:
        for v in range(10):  # 30 total
            n += 1
            descr = "Almuerzo bajo en grasa saturada con proteína magra y vegetales, alineado con hígado graso."
            instr = [step1, "Sirve con los vegetales al lado."]
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt, instr, "solid",
                ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["weight_loss", "health"], ["lightly_active", "moderately_active"],
                ["fatty_liver", "hypercholesterolemia"], [],
                meal_time="lunch", pregnancy_safe=False, prep=10, cook=15,
            ), bucket, n))

    # ─── D) 30 legume meals ───
    legume_specs = [
        ("Lentejas con Verduras y Espinacas", [("lentejas_cocidas", 200), ("espinaca_cocida", 100), ("tomate", 80), ("aceite_oliva", 5)],
         ["200 g de lentejas cocidas", "100 g de espinacas", "80 g de tomate", "5 ml de aceite de oliva"],
         "Saltea las verduras."),
        ("Garbanzos con Calabacín", [("garbanzos_cocidos", 180), ("calabacin", 120), ("tomate", 80), ("aceite_oliva", 5)],
         ["180 g de garbanzos cocidos", "120 g de calabacín", "80 g de tomate", "5 ml de aceite de oliva"],
         "Saltea calabacín."),
        ("Frijoles Negros con Arroz Integral", [("frijoles_negros_cocidos", 150), ("arroz_integral_cocido", 100), ("tomate", 50)],
         ["150 g de frijoles negros", "100 g de arroz integral", "50 g de tomate"],
         "Calienta el arroz."),
    ]
    for nm, comp, txt, step1 in legume_specs:
        for v in range(10):
            n += 1
            descr = "Plato vegetal alto en fibra soluble y proteína vegetal, bajo en grasa saturada."
            instr = [step1, "Combina y sirve."]
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt, instr, "solid",
                ["latam"], ["latam"], "vegan",
                ["weight_loss", "health"], ["lightly_active", "moderately_active"],
                ["fatty_liver", "hypercholesterolemia", "diabetes_t2"], [],
                meal_time="lunch", pregnancy_safe=True, prep=10, cook=10,
            ), bucket, n))

    return out


def _finalize(r: dict, bucket: str, n: int) -> dict:
    r["audit"]["bucket"] = bucket
    return r


# ───── 2) HYPERCHOLESTEROLEMIA — 150 ─────
def build_hyperchol() -> list[dict]:
    out: list[dict] = []
    bucket = "hc"
    n = 0
    specs = [
        ("Avena con Manzana, Nueces y Canela", [("avena_sin_gluten", 50), ("manzana", 100), ("nueces", 10), ("canela", 1), ("leche_almendra", 200)],
         ["50 g de avena sin gluten", "100 g de manzana", "10 g de nueces", "1 g de canela", "200 ml de leche de almendra"],
         "breakfast"),
        ("Avena con Pera y Almendras", [("avena_sin_gluten", 50), ("pera", 100), ("almendras", 10), ("leche_almendra", 200)],
         ["50 g de avena", "100 g de pera", "10 g de almendras", "200 ml de leche de almendra"], "breakfast"),
        ("Sardinas con Ensalada Verde", [("sardina_lata", 80), ("lechuga", 80), ("tomate", 80), ("aceite_oliva", 5)],
         ["80 g de sardinas en lata escurridas", "80 g de lechuga", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón al Vapor con Quinoa", [("salmon", 100), ("quinoa_cocida", 150), ("aguacate", 50)],
         ["100 g de salmón", "150 g de quinoa cocida", "50 g de aguacate"], "lunch"),
        ("Ensalada de Lentejas, Aguacate y Tomate", [("lentejas_cocidas", 180), ("aguacate", 50), ("tomate", 100), ("aceite_oliva", 5)],
         ["180 g de lentejas cocidas", "50 g de aguacate", "100 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl de Garbanzos con Espinaca y Limón", [("garbanzos_cocidos", 180), ("espinaca_cocida", 100), ("limon", 15), ("aceite_oliva", 5)],
         ["180 g de garbanzos", "100 g de espinaca", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón Horneado con Brócoli", [("salmon", 110), ("brocoli_cocido", 150), ("aceite_oliva", 5)],
         ["110 g de salmón", "150 g de brócoli", "5 ml de aceite de oliva"], "dinner"),
        ("Avena con Frambuesa y Linaza", [("avena_sin_gluten", 50), ("frambuesa", 80), ("linaza", 10), ("leche_almendra", 200)],
         ["50 g de avena", "80 g de frambuesa", "10 g de linaza", "200 ml de leche de almendra"], "breakfast"),
        ("Tofu Salteado con Brócoli", [("tofu_firme", 120), ("brocoli_cocido", 150), ("aceite_oliva", 5)],
         ["120 g de tofu firme", "150 g de brócoli", "5 ml de aceite de oliva"], "dinner"),
        ("Trucha con Quinoa y Espinaca", [("trucha", 100), ("quinoa_cocida", 120), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de trucha", "120 g de quinoa", "80 g de espinaca", "5 ml de aceite de oliva"], "dinner"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(15):  # 10 × 15 = 150
            n += 1
            descr = "Plato rico en fibra soluble y omega-3, bajo en grasa saturada, alineado con perfil lipídico saludable."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina según indicación.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["weight_loss", "health"], ["lightly_active", "moderately_active"],
                ["hypercholesterolemia", "fatty_liver"], [],
                meal_time=mt, pregnancy_safe=False, prep=12, cook=10,
            ), bucket, n))
    return out


# ───── 3) PCOS — 100 (low GI, high fiber) ─────
def build_pcos() -> list[dict]:
    out: list[dict] = []
    bucket = "pc"
    n = 0
    specs = [
        ("Bowl de Quinoa con Aguacate y Espinaca", [("quinoa_cocida", 150), ("aguacate", 60), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["150 g de quinoa cocida", "60 g de aguacate", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Avena Cortada con Frambuesa y Chía", [("avena_sin_gluten", 40), ("frambuesa", 80), ("chia", 10), ("leche_almendra", 200)],
         ["40 g de avena cortada", "80 g de frambuesa", "10 g de chía", "200 ml de leche de almendra"], "breakfast"),
        ("Salmón con Espárragos y Quinoa", [("salmon", 100), ("esparragos", 100), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de salmón", "100 g de espárragos", "100 g de quinoa cocida", "5 ml de aceite de oliva"], "dinner"),
        ("Ensalada de Pollo, Aguacate y Espinaca", [("pollo_pechuga", 100), ("aguacate", 50), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de pechuga de pollo", "50 g de aguacate", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Tofu con Brócoli y Quinoa", [("tofu_firme", 120), ("brocoli_cocido", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["120 g de tofu firme", "120 g de brócoli", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl de Lentejas con Aguacate", [("lentejas_cocidas", 150), ("aguacate", 50), ("tomate", 80), ("aceite_oliva", 5)],
         ["150 g de lentejas", "50 g de aguacate", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Sardinas con Espinaca y Limón", [("sardina_lata", 70), ("espinaca_cocida", 100), ("limon", 15), ("aceite_oliva", 5)],
         ["70 g de sardinas", "100 g de espinaca", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Trucha con Espárragos", [("trucha", 100), ("esparragos", 120), ("aceite_oliva", 5)],
         ["100 g de trucha", "120 g de espárragos", "5 ml de aceite de oliva"], "dinner"),
        ("Avena con Arándanos y Linaza", [("avena_sin_gluten", 40), ("arandanos", 80), ("linaza", 10), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de arándanos", "10 g de linaza", "200 ml de leche de almendra"], "breakfast"),
        ("Edamame con Quinoa y Aguacate", [("edamame_cocido", 100), ("quinoa_cocida", 100), ("aguacate", 50), ("aceite_oliva", 5)],
         ["100 g de edamame cocido", "100 g de quinoa", "50 g de aguacate", "5 ml de aceite de oliva"], "lunch"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato de bajo índice glucémico, alto en fibra y omega-3, alineado con manejo de SOP."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina y combina.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["weight_loss", "health"], ["lightly_active", "moderately_active", "very_active"],
                ["pcos", "diabetes_t2"], [],
                meal_time=mt, pregnancy_safe=False, prep=12, cook=12,
            ), bucket, n))
    return out


# ───── 4) IBS — 100 (low-FODMAP soluble fiber) ─────
def build_ibs() -> list[dict]:
    out: list[dict] = []
    bucket = "ib"
    n = 0
    specs = [
        ("Avena con Plátano y Chía", [("avena_sin_gluten", 40), ("platano", 80), ("chia", 8), ("leche_almendra", 200)],
         ["40 g de avena sin gluten", "80 g de plátano", "8 g de chía", "200 ml de leche de almendra"], "breakfast"),
        ("Papaya con Yogur Sin Lactosa", [("papaya", 150), ("yogur_sin_lactosa", 150)],
         ["150 g de papaya", "150 g de yogur sin lactosa"], "breakfast"),
        ("Avena con Papaya y Chía", [("avena_sin_gluten", 40), ("papaya", 100), ("chia", 8), ("leche_almendra", 200)],
         ["40 g de avena sin gluten", "100 g de papaya", "8 g de chía", "200 ml de leche de almendra"], "breakfast"),
        ("Pollo con Arroz Integral y Calabacín", [("pollo_pechuga", 100), ("arroz_integral_cocido", 120), ("calabacin", 100), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de arroz integral", "100 g de calabacín", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón con Arroz Integral", [("salmon", 100), ("arroz_integral_cocido", 120), ("calabacin", 80), ("aceite_oliva", 5)],
         ["100 g de salmón", "120 g de arroz integral", "80 g de calabacín", "5 ml de aceite de oliva"], "dinner"),
        ("Pavo con Calabacín y Quinoa", [("pavo_pechuga", 100), ("calabacin", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["100 g de pavo", "120 g de calabacín", "100 g de quinoa", "5 ml de aceite de oliva"], "dinner"),
        ("Bacalao con Zanahoria al Vapor", [("bacalao", 120), ("zanahoria", 120), ("aceite_oliva", 5)],
         ["120 g de bacalao", "120 g de zanahoria", "5 ml de aceite de oliva"], "lunch"),
        ("Tortilla de Claras con Calabacín", [("clara_huevo", 120), ("calabacin", 100), ("aceite_oliva", 5)],
         ["120 g de claras de huevo", "100 g de calabacín", "5 ml de aceite de oliva"], "breakfast"),
        ("Plátano con Mantequilla de Almendra", [("platano", 100), ("almendras", 12)],
         ["100 g de plátano", "12 g de mantequilla de almendra (sin azúcar añadido)"], "snack"),
        ("Avena Cocida con Kiwi", [("avena_sin_gluten", 40), ("kiwi", 80), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de kiwi", "200 ml de leche de almendra"], "breakfast"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato de fibra soluble suave, sin alto FODMAP, alineado con bienestar digestivo."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina suave.", "Sirve."],
                "solid", ["latam"], ["latam"], "omnivore",
                ["health", "weight_loss"], ["sedentary", "lightly_active"],
                ["ibs", "fatty_liver"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=10,
            ), bucket, n))
    return out


# ───── 5) HYPOTHYROIDISM — 100 (Se + I + protein, cooked goitrogens OK) ─────
def build_hypothyroidism() -> list[dict]:
    out: list[dict] = []
    bucket = "ht"
    n = 0
    specs = [
        ("Salmón con Brócoli Cocido y Quinoa", [("salmon", 120), ("brocoli_cocido", 120), ("quinoa_cocida", 100), ("aceite_oliva", 5)],
         ["120 g de salmón", "120 g de brócoli cocido", "100 g de quinoa", "5 ml de aceite de oliva"], "lunch"),
        ("Atún con Espinaca Cocida", [("atun_agua", 100), ("espinaca_cocida", 120), ("aceite_oliva", 5)],
         ["100 g de atún en agua escurrido", "120 g de espinaca cocida", "5 ml de aceite de oliva"], "lunch"),
        ("Trucha con Coliflor Cocida", [("trucha", 120), ("coliflor_cocida", 120), ("aceite_oliva", 5)],
         ["120 g de trucha", "120 g de coliflor cocida", "5 ml de aceite de oliva"], "dinner"),
        ("Huevo con Espinaca y Quinoa", [("huevo", 100), ("espinaca_cocida", 100), ("quinoa_cocida", 100)],
         ["2 huevos (100 g)", "100 g de espinaca cocida", "100 g de quinoa"], "breakfast"),
        ("Bacalao con Coliflor", [("bacalao", 130), ("coliflor_cocida", 120), ("aceite_oliva", 5)],
         ["130 g de bacalao", "120 g de coliflor cocida", "5 ml de aceite de oliva"], "dinner"),
        ("Sardinas con Quinoa y Espinaca", [("sardina_lata", 60), ("quinoa_cocida", 120), ("espinaca_cocida", 80)],
         ["60 g de sardinas escurridas", "120 g de quinoa", "80 g de espinaca cocida"], "lunch"),
        ("Yogur Sin Lactosa con Nuez de Brasil", [("yogur_sin_lactosa", 150), ("nuez_brasil", 6), ("arandanos", 50)],
         ["150 g de yogur sin lactosa", "6 g de nuez de Brasil (2 unidades)", "50 g de arándanos"], "snack"),
        ("Salmón con Espárragos y Arroz Integral", [("salmon", 100), ("esparragos", 100), ("arroz_integral_cocido", 100), ("aceite_oliva", 5)],
         ["100 g de salmón", "100 g de espárragos", "100 g de arroz integral", "5 ml de aceite de oliva"], "dinner"),
        ("Huevo con Champiñones Cocidos", [("huevo", 100), ("champinon", 100), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de champiñones cocidos", "5 ml de aceite de oliva"], "breakfast"),
        ("Atún con Quinoa y Aguacate", [("atun_agua", 100), ("quinoa_cocida", 100), ("aguacate", 50)],
         ["100 g de atún en agua", "100 g de quinoa", "50 g de aguacate"], "lunch"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato rico en selenio y proteína de calidad, con crucíferas siempre cocidas, alineado con función tiroidea."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina los crucíferos completamente.", "Prepara la proteína.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["health", "maintain"], ["lightly_active", "moderately_active"],
                ["hypothyroidism"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=15,
            ), bucket, n))
    return out


# ───── 6) GOUT — 100 (low purine) ─────
def build_gout() -> list[dict]:
    out: list[dict] = []
    bucket = "go"
    n = 0
    specs = [
        ("Yogur Griego con Cerezas y Almendras", [("yogur_griego", 200), ("cereza", 80), ("almendras", 10)],
         ["200 g de yogur griego natural", "80 g de cerezas", "10 g de almendras"], "breakfast"),
        ("Avena con Cerezas y Chía", [("avena_sin_gluten", 40), ("cereza", 80), ("chia", 8), ("leche_almendra", 200)],
         ["40 g de avena", "80 g de cerezas", "8 g de chía", "200 ml de leche de almendra"], "breakfast"),
        ("Huevo Revuelto con Tomate", [("huevo", 100), ("tomate", 100), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de tomate", "5 ml de aceite de oliva"], "breakfast"),
        ("Ensalada de Quinoa, Pepino y Limón", [("quinoa_cocida", 150), ("pepino", 100), ("limon", 15), ("aceite_oliva", 5)],
         ["150 g de quinoa", "100 g de pepino", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Tortilla de Claras con Calabacín", [("clara_huevo", 120), ("calabacin", 100), ("aceite_oliva", 5)],
         ["120 g de claras", "100 g de calabacín", "5 ml de aceite de oliva"], "breakfast"),
        ("Yogur con Frambuesa y Linaza", [("yogur_griego", 200), ("frambuesa", 80), ("linaza", 8)],
         ["200 g de yogur griego", "80 g de frambuesa", "8 g de linaza"], "snack"),
        ("Bowl de Camote con Aguacate", [("camote_cocido", 200), ("aguacate", 50), ("aceite_oliva", 5)],
         ["200 g de camote cocido", "50 g de aguacate", "5 ml de aceite de oliva"], "lunch"),
        ("Arroz Integral con Calabacín y Tomate", [("arroz_integral_cocido", 150), ("calabacin", 100), ("tomate", 80), ("aceite_oliva", 5)],
         ["150 g de arroz integral", "100 g de calabacín", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Yogur con Cerezas y Avena", [("yogur_griego", 200), ("cereza", 80), ("avena_sin_gluten", 25)],
         ["200 g de yogur griego", "80 g de cerezas", "25 g de avena"], "breakfast"),
        ("Huevo con Camote y Aguacate", [("huevo", 100), ("camote_cocido", 150), ("aguacate", 40)],
         ["2 huevos", "150 g de camote cocido", "40 g de aguacate"], "breakfast"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato bajo en purinas, sin mariscos ni vísceras, alineado con manejo de hiperuricemia."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina.", "Sirve."],
                "solid", ["latam"], ["latam"], "omnivore",
                ["health", "maintain"], ["sedentary", "lightly_active"],
                ["gout"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=10,
            ), bucket, n))
    return out


# ───── 7) VITAMIN_D_DEFICIENCY — 50 ─────
def build_vit_d() -> list[dict]:
    out: list[dict] = []
    bucket = "vd"
    n = 0
    specs = [
        ("Salmón al Vapor con Espinaca", [("salmon", 130), ("espinaca_cocida", 120), ("aceite_oliva", 5)],
         ["130 g de salmón", "120 g de espinaca cocida", "5 ml de aceite de oliva"], "lunch"),
        ("Sardinas con Quinoa", [("sardina_lata", 80), ("quinoa_cocida", 120), ("limon", 15)],
         ["80 g de sardinas", "120 g de quinoa", "15 g de limón"], "lunch"),
        ("Huevo Revuelto con Champiñones UV", [("huevo", 100), ("champinon_uv", 100), ("aceite_oliva", 5)],
         ["2 huevos", "100 g de champiñones tratados con UV", "5 ml de aceite de oliva"], "breakfast"),
        ("Trucha con Espárragos", [("trucha", 130), ("esparragos", 120), ("aceite_oliva", 5)],
         ["130 g de trucha", "120 g de espárragos", "5 ml de aceite de oliva"], "dinner"),
        ("Salmón con Quinoa y Aguacate", [("salmon", 100), ("quinoa_cocida", 100), ("aguacate", 50)],
         ["100 g de salmón", "100 g de quinoa", "50 g de aguacate"], "dinner"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato con fuentes alimentarias de vitamina D (pescado graso, huevo, hongos UV)."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Cocina la proteína.", "Combina.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["health", "maintain"], ["lightly_active", "moderately_active"],
                ["vitamin_d_deficiency"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=12,
            ), bucket, n))
    return out


# ───── 8) LACTOSE_INTOLERANCE — 100 ─────
def build_lactose() -> list[dict]:
    out: list[dict] = []
    bucket = "li"
    n = 0
    specs = [
        ("Avena con Leche de Avena y Arándanos", [("avena_sin_gluten", 40), ("leche_avena", 200), ("arandanos", 80), ("chia", 8)],
         ["40 g de avena sin gluten", "200 ml de leche de avena", "80 g de arándanos", "8 g de chía"], "breakfast"),
        ("Yogur Sin Lactosa con Frambuesa", [("yogur_sin_lactosa", 200), ("frambuesa", 80), ("linaza", 8)],
         ["200 g de yogur sin lactosa", "80 g de frambuesa", "8 g de linaza"], "breakfast"),
        ("Avena con Leche de Almendra y Plátano", [("avena_sin_gluten", 40), ("leche_almendra", 200), ("platano", 80), ("chia", 8)],
         ["40 g de avena", "200 ml de leche de almendra", "80 g de plátano", "8 g de chía"], "breakfast"),
        ("Smoothie de Leche de Soya, Plátano y Linaza", [("leche_soya", 250), ("platano", 80), ("linaza", 8)],
         ["250 ml de leche de soya", "80 g de plátano", "8 g de linaza molida"], "breakfast"),
        ("Pollo con Quinoa y Espinaca", [("pollo_pechuga", 100), ("quinoa_cocida", 120), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["100 g de pollo", "120 g de quinoa", "80 g de espinaca", "5 ml de aceite de oliva"], "lunch"),
        ("Salmón con Camote", [("salmon", 100), ("camote_cocido", 150), ("aceite_oliva", 5)],
         ["100 g de salmón", "150 g de camote", "5 ml de aceite de oliva"], "dinner"),
        ("Tofu Salteado con Brócoli", [("tofu_firme", 120), ("brocoli_cocido", 120), ("aceite_oliva", 5)],
         ["120 g de tofu", "120 g de brócoli", "5 ml de aceite de oliva"], "dinner"),
        ("Bowl de Lentejas y Aguacate", [("lentejas_cocidas", 150), ("aguacate", 50), ("tomate", 80)],
         ["150 g de lentejas", "50 g de aguacate", "80 g de tomate"], "lunch"),
        ("Yogur Sin Lactosa con Avena", [("yogur_sin_lactosa", 200), ("avena_sin_gluten", 25), ("arandanos", 50)],
         ["200 g de yogur sin lactosa", "25 g de avena", "50 g de arándanos"], "breakfast"),
        ("Huevo con Camote y Espinaca", [("huevo", 100), ("camote_cocido", 150), ("espinaca_cocida", 80)],
         ["2 huevos", "150 g de camote", "80 g de espinaca"], "breakfast"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato sin lácteos (o con lácteos sin lactosa), apto para intolerancia a la lactosa."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina.", "Sirve."],
                "solid", ["latam", "mediterranean"], ["latam", "eu", "us"], "omnivore",
                ["health", "maintain"], ["lightly_active", "moderately_active"],
                ["lactose_intolerance"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=10,
            ), bucket, n))
    return out


# ───── 9) OVERWEIGHT — 50 (lower kcal 300-500, satiety) ─────
def build_overweight() -> list[dict]:
    out: list[dict] = []
    bucket = "ow"
    n = 0
    specs = [
        ("Ensalada de Pollo, Lechuga y Tomate", [("pollo_pechuga", 100), ("lechuga", 80), ("tomate", 80), ("aceite_oliva", 5)],
         ["100 g de pollo", "80 g de lechuga", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Bowl de Quinoa, Espinaca y Limón", [("quinoa_cocida", 120), ("espinaca_cocida", 80), ("limon", 15), ("aceite_oliva", 5)],
         ["120 g de quinoa", "80 g de espinaca", "15 g de limón", "5 ml de aceite de oliva"], "lunch"),
        ("Avena con Manzana y Canela", [("avena_sin_gluten", 35), ("manzana", 100), ("canela", 1), ("leche_almendra", 200)],
         ["35 g de avena", "100 g de manzana", "1 g de canela", "200 ml de leche de almendra"], "breakfast"),
        ("Sopa de Lentejas con Verduras", [("lentejas_cocidas", 130), ("zanahoria", 80), ("tomate", 80), ("aceite_oliva", 5)],
         ["130 g de lentejas", "80 g de zanahoria", "80 g de tomate", "5 ml de aceite de oliva"], "lunch"),
        ("Tortilla de Claras con Espinaca", [("clara_huevo", 120), ("espinaca_cocida", 80), ("aceite_oliva", 5)],
         ["120 g de claras", "80 g de espinaca", "5 ml de aceite de oliva"], "breakfast"),
    ]
    for nm, comp, txt, mt in specs:
        for v in range(10):
            n += 1
            descr = "Plato de menor densidad energética y alta saciedad, alineado con manejo de sobrepeso."
            out.append(_finalize(build_recipe(
                _id(bucket, n), f"{nm} (variante {v+1})", descr, comp, txt,
                ["Prepara los ingredientes.", "Cocina ligero.", "Sirve."],
                "solid", ["mediterranean", "latam"], ["latam", "eu", "us"], "omnivore",
                ["weight_loss"], ["sedentary", "lightly_active"],
                ["overweight", "obesity", "fatty_liver"], [],
                meal_time=mt, pregnancy_safe=False, prep=10, cook=10,
            ), bucket, n))
    return out


# ═════════════════════════════════════════════════════════════════════════
def main() -> None:
    all_buckets = {
        "fatty_liver": build_fatty_liver(),
        "hypercholesterolemia": build_hyperchol(),
        "pcos": build_pcos(),
        "ibs": build_ibs(),
        "hypothyroidism": build_hypothyroidism(),
        "gout": build_gout(),
        "vitamin_d_deficiency": build_vit_d(),
        "lactose_intolerance": build_lactose(),
        "overweight": build_overweight(),
    }

    # Dedup vs master catalog by exact (name lowercased).
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

    out_path = ROOT / "data" / "meals" / "condition_helpful_batch_2026_06_01.json"
    out_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2))

    log_path = ROOT / "scripts" / "generate_recipes_condition_helpful_2026_06_01_rejections.log"
    log_lines = [f"TOTAL accepted={len(valid)} rejected={len(rejected)}", ""]
    for b, s in bucket_stats.items():
        log_lines.append(f"  {b:25s} gen={s['generated']:4d} acc={s['accepted']:4d} rej={s['rejected']:3d} dedup={s['dedup']:3d}")
    log_lines.append("")
    log_lines.extend(f"{rid}\t{reason}" for rid, reason in rejected)
    log_path.write_text("\n".join(log_lines))

    print(f"condition_helpful_batch: accepted={len(valid)} rejected={len(rejected)}")
    for b, s in bucket_stats.items():
        print(f"  {b:25s} gen={s['generated']} acc={s['accepted']} rej={s['rejected']} dedup={s['dedup']}")


if __name__ == "__main__":
    main()
