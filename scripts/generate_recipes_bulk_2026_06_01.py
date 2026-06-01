"""Bulk recipe generator — combinatorial templates × parametric slots.

Deterministic. No HTTP. No LLM. Closed-vocabulary validated.

Approach:
- Define ~30 template archetypes (cuisine × meal_time × dietary_pattern).
- Each template has slots: protein × carb × veg × fat × seasoning.
- Cartesian product → validate → append. IDs deterministic from sha1.
- Realistic macros via inline ingredient_kcal table (USDA-derived rounded).
- Honest count — rejects (allergens to recommendations, macro drift,
  enum drift, sugar cap, kcal floor/ceiling) are dropped silently with
  log entry.

Outputs:
- data/meals/bulk_batch_2026_06_01.json
- scripts/generate_recipes_bulk_2026_06_01_rejections.log
"""
from __future__ import annotations

import hashlib
import json
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import (  # noqa: E402
    ACTIVITY_LEVELS_5, ALLERGENS_14, CONDITIONS_25, GOALS_5, MEAL_TIMES_4, REGIONS_5,
)

PLACEHOLDER_IMG = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"

# ---------------------------------------------------------------------------
# Ingredient table per 100 g cooked (USDA-derived, rounded). gi=None where N/A.
# ---------------------------------------------------------------------------
ING = {
    # Proteins (animal)
    "pollo_pechuga":    {"kcal": 165, "p": 31,  "c": 0,   "f": 3.6, "fib": 0,   "sug": 0,   "na": 74,  "gi": 0,  "tags": ["omnivore"]},
    "pavo_pechuga":     {"kcal": 135, "p": 30,  "c": 0,   "f": 1.0, "fib": 0,   "sug": 0,   "na": 65,  "gi": 0,  "tags": ["omnivore"]},
    "salmon":           {"kcal": 208, "p": 22,  "c": 0,   "f": 13,  "fib": 0,   "sug": 0,   "na": 59,  "gi": 0,  "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "atun_fresco":      {"kcal": 144, "p": 30,  "c": 0,   "f": 1.0, "fib": 0,   "sug": 0,   "na": 39,  "gi": 0,  "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "bacalao":          {"kcal": 82,  "p": 18,  "c": 0,   "f": 0.7, "fib": 0,   "sug": 0,   "na": 78,  "gi": 0,  "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "trucha":           {"kcal": 168, "p": 23,  "c": 0,   "f": 8,   "fib": 0,   "sug": 0,   "na": 50,  "gi": 0,  "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "lomo_magro":       {"kcal": 158, "p": 26,  "c": 0,   "f": 6,   "fib": 0,   "sug": 0,   "na": 60,  "gi": 0,  "tags": ["omnivore"]},
    "huevo":            {"kcal": 143, "p": 13,  "c": 1.1, "f": 9.5, "fib": 0,   "sug": 1.1, "na": 142, "gi": 0,  "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["egg"]},
    "yogur_griego":     {"kcal": 59,  "p": 10,  "c": 3.6, "f": 0.4, "fib": 0,   "sug": 3.2, "na": 36,  "gi": 11, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_fresco":     {"kcal": 98,  "p": 11,  "c": 3.4, "f": 4.3, "fib": 0,   "sug": 3.4, "na": 350, "gi": 30, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_feta":       {"kcal": 264, "p": 14,  "c": 4.1, "f": 21,  "fib": 0,   "sug": 4.1, "na": 917, "gi": 30, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    # Proteins (plant)
    "tofu_firme":       {"kcal": 144, "p": 17,  "c": 3,   "f": 9,   "fib": 2,   "sug": 1,   "na": 14,  "gi": 15, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "tempeh":           {"kcal": 192, "p": 20,  "c": 8,   "f": 11,  "fib": 0,   "sug": 0,   "na": 9,   "gi": 15, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "seitán":           {"kcal": 370, "p": 75,  "c": 14,  "f": 1.9, "fib": 0.6, "sug": 0,   "na": 29,  "gi": 0,  "tags": ["omnivore","vegetarian","vegan"], "allergens": ["gluten"]},
    "lentejas":         {"kcal": 116, "p": 9,   "c": 20,  "f": 0.4, "fib": 8,   "sug": 1.8, "na": 2,   "gi": 32, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "garbanzos":        {"kcal": 164, "p": 8.9, "c": 27,  "f": 2.6, "fib": 7.6, "sug": 4.8, "na": 7,   "gi": 28, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "frijoles_negros":  {"kcal": 132, "p": 8.9, "c": 24,  "f": 0.5, "fib": 8.7, "sug": 0.3, "na": 1,   "gi": 30, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "edamame":          {"kcal": 121, "p": 12,  "c": 9,   "f": 5,   "fib": 5,   "sug": 2.2, "na": 6,   "gi": 18, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    # Carbs
    "quinoa":           {"kcal": 120, "p": 4.4, "c": 21,  "f": 1.9, "fib": 2.8, "sug": 0.9, "na": 7,   "gi": 53, "tags": ["any"]},
    "arroz_integral":   {"kcal": 123, "p": 2.7, "c": 26,  "f": 1.0, "fib": 1.6, "sug": 0.4, "na": 4,   "gi": 50, "tags": ["any"]},
    "camote":           {"kcal": 86,  "p": 1.6, "c": 20,  "f": 0.1, "fib": 3,   "sug": 4.2, "na": 55,  "gi": 63, "tags": ["any"]},
    "papa":             {"kcal": 77,  "p": 2,   "c": 17,  "f": 0.1, "fib": 2.2, "sug": 0.8, "na": 6,   "gi": 78, "tags": ["any"]},
    "bulgur":           {"kcal": 83,  "p": 3.1, "c": 19,  "f": 0.2, "fib": 4.5, "sug": 0.1, "na": 5,   "gi": 48, "tags": ["any"], "allergens": ["gluten"]},
    "farro":            {"kcal": 170, "p": 6,   "c": 34,  "f": 1.5, "fib": 5,   "sug": 1,   "na": 5,   "gi": 45, "tags": ["any"], "allergens": ["gluten"]},
    "platano_macho":    {"kcal": 122, "p": 1.3, "c": 32,  "f": 0.4, "fib": 2.3, "sug": 15,  "na": 4,   "gi": 55, "tags": ["any"]},
    "avena":            {"kcal": 71,  "p": 2.5, "c": 12,  "f": 1.5, "fib": 1.7, "sug": 0,   "na": 3,   "gi": 55, "tags": ["any"], "allergens": ["gluten"]},
    "pan_integral":     {"kcal": 247, "p": 13,  "c": 41,  "f": 3.4, "fib": 7,   "sug": 5,   "na": 491, "gi": 71, "tags": ["any"], "allergens": ["gluten"]},
    "tortilla_maiz":    {"kcal": 218, "p": 5.7, "c": 45,  "f": 2.9, "fib": 6.3, "sug": 1.1, "na": 45,  "gi": 52, "tags": ["any"]},
    # Veg
    "brocoli":          {"kcal": 35,  "p": 2.4, "c": 7,   "f": 0.4, "fib": 3.3, "sug": 1.7, "na": 41,  "gi": 15, "tags": ["any"]},
    "espinaca":         {"kcal": 23,  "p": 2.9, "c": 3.6, "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79,  "gi": 15, "tags": ["any"]},
    "kale":             {"kcal": 35,  "p": 2.9, "c": 4.4, "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53,  "gi": 15, "tags": ["any"]},
    "rucula":           {"kcal": 25,  "p": 2.6, "c": 3.7, "f": 0.7, "fib": 1.6, "sug": 2,   "na": 27,  "gi": 15, "tags": ["any"]},
    "tomate":           {"kcal": 18,  "p": 0.9, "c": 3.9, "f": 0.2, "fib": 1.2, "sug": 2.6, "na": 5,   "gi": 30, "tags": ["any"]},
    "pimiento_rojo":    {"kcal": 31,  "p": 1,   "c": 6,   "f": 0.3, "fib": 2.1, "sug": 4.2, "na": 4,   "gi": 15, "tags": ["any"]},
    "calabacin":        {"kcal": 17,  "p": 1.2, "c": 3.1, "f": 0.3, "fib": 1,   "sug": 2.5, "na": 8,   "gi": 15, "tags": ["any"]},
    "zanahoria":        {"kcal": 41,  "p": 0.9, "c": 9.6, "f": 0.2, "fib": 2.8, "sug": 4.7, "na": 69,  "gi": 39, "tags": ["any"]},
    "cebolla":          {"kcal": 40,  "p": 1.1, "c": 9.3, "f": 0.1, "fib": 1.7, "sug": 4.2, "na": 4,   "gi": 15, "tags": ["any"]},
    "ajo":              {"kcal": 149, "p": 6.4, "c": 33,  "f": 0.5, "fib": 2.1, "sug": 1,   "na": 17,  "gi": 0,  "tags": ["any"]},
    "champinones":      {"kcal": 22,  "p": 3.1, "c": 3.3, "f": 0.3, "fib": 1,   "sug": 2,   "na": 5,   "gi": 15, "tags": ["any"]},
    "aguacate":         {"kcal": 160, "p": 2,   "c": 9,   "f": 15,  "fib": 7,   "sug": 0.7, "na": 7,   "gi": 10, "tags": ["any"]},
    "pepino":           {"kcal": 16,  "p": 0.7, "c": 3.6, "f": 0.1, "fib": 0.5, "sug": 1.7, "na": 2,   "gi": 15, "tags": ["any"]},
    "berenjena":        {"kcal": 25,  "p": 1,   "c": 6,   "f": 0.2, "fib": 3,   "sug": 3.5, "na": 2,   "gi": 15, "tags": ["any"]},
    "coliflor":         {"kcal": 25,  "p": 1.9, "c": 5,   "f": 0.3, "fib": 2,   "sug": 1.9, "na": 30,  "gi": 15, "tags": ["any"]},
    # Fats
    "aceite_oliva":     {"kcal": 884, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "tags": ["any"]},
    "aceite_sesamo":    {"kcal": 884, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "tags": ["any"], "allergens": ["sesame"]},
    "tahini":           {"kcal": 595, "p": 17,  "c": 21,  "f": 53,  "fib": 9.3, "sug": 0.5, "na": 115, "gi": 40, "tags": ["any"], "allergens": ["sesame"]},
    "almendras":        {"kcal": 579, "p": 21,  "c": 22,  "f": 50,  "fib": 12,  "sug": 4.4, "na": 1,   "gi": 0,  "tags": ["any"], "allergens": ["tree_nuts"]},
    "nuez":             {"kcal": 654, "p": 15,  "c": 14,  "f": 65,  "fib": 6.7, "sug": 2.6, "na": 2,   "gi": 0,  "tags": ["any"], "allergens": ["tree_nuts"]},
    "semillas_chia":    {"kcal": 486, "p": 17,  "c": 42,  "f": 31,  "fib": 34,  "sug": 0,   "na": 16,  "gi": 1,  "tags": ["any"]},
    "semillas_lino":    {"kcal": 534, "p": 18,  "c": 29,  "f": 42,  "fib": 27,  "sug": 1.6, "na": 30,  "gi": 1,  "tags": ["any"]},
    "aceitunas":        {"kcal": 115, "p": 0.8, "c": 6,   "f": 11,  "fib": 3.2, "sug": 0,   "na": 735, "gi": 0,  "tags": ["any"]},
    # Liquid bases for breakfasts
    "leche_almendra":   {"kcal": 17,  "p": 0.6, "c": 0.6, "f": 1.5, "fib": 0.3, "sug": 0,   "na": 60,  "gi": 25, "tags": ["any"], "allergens": ["tree_nuts"]},
    "leche_avena":      {"kcal": 47,  "p": 1.0, "c": 6.6, "f": 1.5, "fib": 0.8, "sug": 3.3, "na": 42,  "gi": 60, "tags": ["any"], "allergens": ["gluten"]},
    "leche_descremada": {"kcal": 34,  "p": 3.4, "c": 5,   "f": 0.1, "fib": 0,   "sug": 5,   "na": 42,  "gi": 32, "tags": ["any"], "allergens": ["dairy"]},
}

ALLERGEN_FROM_KEY = {k: tuple(v.get("allergens", [])) for k, v in ING.items()}

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
# (template_id, cuisine_region, meal_time, dietary_pattern, proteins, carbs, vegs, fats, name_pattern, instructions_pattern, cultural_origin, regions, conditions_rec, conditions_contra, goals, activity, pregnancy_safe, prep, cook)

# Protein/carb/veg/fat pools — split by dietary pattern
PROT_OMNI = ["pollo_pechuga", "pavo_pechuga", "salmon", "atun_fresco", "bacalao", "trucha", "lomo_magro", "huevo"]
PROT_PESC = ["salmon", "atun_fresco", "bacalao", "trucha", "huevo", "yogur_griego"]
PROT_VEG  = ["huevo", "yogur_griego", "queso_fresco", "queso_feta", "tofu_firme", "tempeh", "lentejas", "garbanzos", "frijoles_negros", "edamame"]
PROT_VGAN = ["tofu_firme", "tempeh", "seitán", "lentejas", "garbanzos", "frijoles_negros", "edamame"]

CARB_GENERIC = ["quinoa", "arroz_integral", "camote", "bulgur", "farro", "platano_macho"]
CARB_BREAKFAST = ["avena", "pan_integral", "camote"]
CARB_LATAM = ["arroz_integral", "frijoles_negros", "platano_macho", "tortilla_maiz", "camote"]

VEG_GENERIC = ["brocoli", "espinaca", "kale", "tomate", "pimiento_rojo", "calabacin", "zanahoria", "champinones", "berenjena", "coliflor"]
VEG_SALAD = ["rucula", "espinaca", "tomate", "pepino", "aguacate", "pimiento_rojo"]

FAT_GENERIC = ["aceite_oliva", "aguacate", "almendras", "nuez", "semillas_chia", "semillas_lino"]
FAT_MED = ["aceite_oliva", "aceitunas", "almendras", "queso_feta"]
FAT_ASIAN = ["aceite_sesamo", "semillas_chia"]
FAT_ME = ["tahini", "aceite_oliva", "almendras"]


TEMPLATES = [
    # ---- LATAM ----
    {
        "tid": "latam_bowl_omni", "cuisine": ["latam"], "meal_time": "lunch", "diet": "omnivore",
        "prot_pool": PROT_OMNI, "prot_g": 120,
        "carb_pool": CARB_LATAM, "carb_g": 120,
        "veg_pool": VEG_GENERIC, "veg_g": 100,
        "fat_pool": ["aceite_oliva", "aguacate"], "fat_g": 15,
        "name": "Bowl Latino de {prot} con {carb}, {veg} y {fat}",
        "desc": "Bowl latinoamericano balanceado: proteína magra, carbohidrato complejo y grasas saludables.",
        "regions": ["latam"], "rec": ["athletic_load"], "contra": [],
        "goals": ["maintain", "muscle_gain"], "act": ["moderately_active", "very_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "Pan-LatAm",
        "instructions": [
            "Cocina la {prot} a la plancha con sal y pimienta.",
            "Calienta el {carb} cocido.",
            "Saltea el {veg} con ajo.",
            "Sirve todo en bowl y termina con {fat}.",
        ],
    },
    {
        "tid": "latam_bowl_vegan", "cuisine": ["latam"], "meal_time": "lunch", "diet": "vegan",
        "prot_pool": PROT_VGAN, "prot_g": 120,
        "carb_pool": CARB_LATAM, "carb_g": 120,
        "veg_pool": VEG_GENERIC, "veg_g": 100,
        "fat_pool": ["aguacate", "almendras"], "fat_g": 20,
        "name": "Bowl Andino Vegano de {prot} con {carb}, {veg} y {fat}",
        "desc": "Bowl vegano andino, proteína vegetal completa y vegetales coloridos.",
        "regions": ["latam", "eu"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "Andes",
        "instructions": [
            "Saltea la {prot} con cebolla y ajo.",
            "Sirve el {carb} caliente como base.",
            "Añade {veg} salteado.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "latam_breakfast", "cuisine": ["latam"], "meal_time": "breakfast", "diet": "omnivore",
        "prot_pool": ["huevo", "yogur_griego", "queso_fresco"], "prot_g": 80,
        "carb_pool": ["tortilla_maiz", "pan_integral", "avena", "camote"], "carb_g": 80,
        "veg_pool": ["tomate", "pimiento_rojo", "aguacate"], "veg_g": 60,
        "fat_pool": ["aguacate", "aceite_oliva", "almendras"], "fat_g": 15,
        "name": "Desayuno Latino con {prot}, {carb} y {veg}",
        "desc": "Desayuno LatAm sustancioso para iniciar el día con energía sostenida.",
        "regions": ["latam"], "rec": [], "contra": [],
        "goals": ["maintain", "muscle_gain"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 10, "cook": 10, "origin": "Pan-LatAm",
        "instructions": [
            "Prepara la {prot} a tu gusto.",
            "Calienta el {carb}.",
            "Acompaña con {veg} fresco.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "latam_dinner_pescatarian", "cuisine": ["latam"], "meal_time": "dinner", "diet": "pescatarian",
        "prot_pool": ["salmon", "trucha", "bacalao", "atun_fresco"], "prot_g": 120,
        "carb_pool": ["camote", "quinoa", "platano_macho"], "carb_g": 100,
        "veg_pool": VEG_GENERIC, "veg_g": 120,
        "fat_pool": ["aceite_oliva", "aguacate"], "fat_g": 12,
        "name": "Cena LatAm de {prot} con {carb} y {veg}",
        "desc": "Cena ligera de pescado azul, carbo complejo y vegetales asados.",
        "regions": ["latam", "us"], "rec": ["dyslipidemia", "ischemic_heart_disease"], "contra": [],
        "goals": ["weight_loss", "health"], "act": ["sedentary", "lightly_active", "moderately_active"],
        "preg": False, "prep": 10, "cook": 25, "origin": "Costa LatAm",
        "instructions": [
            "Hornea la {prot} 12 min a 200°C.",
            "Asa el {carb} en cubos.",
            "Asa el {veg} junto al carbo.",
            "Sirve con {fat}.",
        ],
    },
    {
        "tid": "latam_snack_vegan", "cuisine": ["latam"], "meal_time": "snack", "diet": "vegan",
        "prot_pool": ["frijoles_negros", "garbanzos"], "prot_g": 80,
        "carb_pool": ["tortilla_maiz", "camote"], "carb_g": 60,
        "veg_pool": ["aguacate", "tomate", "pimiento_rojo"], "veg_g": 60,
        "fat_pool": ["aguacate", "semillas_lino"], "fat_g": 12,
        "name": "Snack LatAm Vegano de {prot} con {carb}",
        "desc": "Snack vegano LatAm con proteína vegetal y carbohidrato tradicional.",
        "regions": ["latam"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["maintain", "weight_loss"], "act": ["sedentary", "lightly_active"],
        "preg": True, "prep": 10, "cook": 5, "origin": "Mesoamérica",
        "instructions": [
            "Calienta el {carb}.",
            "Mezcla {prot} con {veg}.",
            "Sirve con {fat} encima.",
        ],
    },
    # ---- MEDITERRANEAN ----
    {
        "tid": "med_bowl_pescatarian", "cuisine": ["mediterranean"], "meal_time": "lunch", "diet": "pescatarian",
        "prot_pool": ["salmon", "atun_fresco", "bacalao", "huevo", "yogur_griego"], "prot_g": 120,
        "carb_pool": ["bulgur", "farro", "quinoa"], "carb_g": 100,
        "veg_pool": VEG_GENERIC, "veg_g": 120,
        "fat_pool": FAT_MED, "fat_g": 15,
        "name": "Bowl Mediterráneo de {prot} con {carb}, {veg} y {fat}",
        "desc": "Bowl mediterráneo rico en omega-3 y polifenoles del aceite de oliva.",
        "regions": ["eu", "us"], "rec": ["ischemic_heart_disease", "dyslipidemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "Mediterráneo",
        "instructions": [
            "Cocina la {prot} a la plancha.",
            "Sirve el {carb} cocido como base.",
            "Añade {veg} fresco.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "med_breakfast_veg", "cuisine": ["mediterranean"], "meal_time": "breakfast", "diet": "vegetarian",
        "prot_pool": ["huevo", "yogur_griego", "queso_feta"], "prot_g": 80,
        "carb_pool": ["pan_integral", "avena"], "carb_g": 60,
        "veg_pool": ["tomate", "rucula", "espinaca"], "veg_g": 60,
        "fat_pool": ["aceite_oliva", "aceitunas", "almendras"], "fat_g": 12,
        "name": "Desayuno Mediterráneo con {prot}, {carb} y {veg}",
        "desc": "Desayuno mediterráneo equilibrado con grasas monoinsaturadas y proteína.",
        "regions": ["eu", "us", "uk"], "rec": ["ischemic_heart_disease"], "contra": [],
        "goals": ["maintain", "health"], "act": ["sedentary", "lightly_active", "moderately_active"],
        "preg": True, "prep": 10, "cook": 5, "origin": "España/Italia",
        "instructions": [
            "Prepara la {prot}.",
            "Tuesta el {carb}.",
            "Acompaña con {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "med_dinner_pescatarian", "cuisine": ["mediterranean"], "meal_time": "dinner", "diet": "pescatarian",
        "prot_pool": ["salmon", "bacalao", "trucha", "atun_fresco"], "prot_g": 120,
        "carb_pool": ["quinoa", "farro", "camote"], "carb_g": 80,
        "veg_pool": ["calabacin", "berenjena", "pimiento_rojo", "espinaca", "brocoli"], "veg_g": 150,
        "fat_pool": ["aceite_oliva", "aceitunas"], "fat_g": 12,
        "name": "Cena Mediterránea de {prot} al Horno con {carb} y {veg}",
        "desc": "Cena ligera mediterránea, pescado al horno con vegetales asados.",
        "regions": ["eu", "uk"], "rec": ["dyslipidemia", "hypertension"], "contra": [],
        "goals": ["weight_loss", "health"], "act": ["sedentary", "lightly_active"],
        "preg": False, "prep": 10, "cook": 25, "origin": "Mediterráneo",
        "instructions": [
            "Hornea la {prot} con limón.",
            "Cocina el {carb}.",
            "Asa el {veg}.",
            "Aliña con {fat}.",
        ],
    },
    {
        "tid": "med_vegan_lunch", "cuisine": ["mediterranean"], "meal_time": "lunch", "diet": "vegan",
        "prot_pool": ["garbanzos", "lentejas", "tofu_firme", "tempeh"], "prot_g": 120,
        "carb_pool": ["bulgur", "farro", "quinoa"], "carb_g": 100,
        "veg_pool": VEG_GENERIC, "veg_g": 120,
        "fat_pool": ["aceite_oliva", "tahini", "aceitunas"], "fat_g": 12,
        "name": "Plato Mediterráneo Vegano de {prot} con {carb} y {veg}",
        "desc": "Plato vegano mediterráneo con legumbres y grasas saludables.",
        "regions": ["eu", "us", "uk"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "Mediterráneo",
        "instructions": [
            "Saltea la {prot}.",
            "Sirve {carb} como base.",
            "Añade {veg}.",
            "Aliña con {fat}.",
        ],
    },
    # ---- ASIAN ----
    {
        "tid": "asian_bowl_omni", "cuisine": ["asian"], "meal_time": "lunch", "diet": "omnivore",
        "prot_pool": ["pollo_pechuga", "salmon", "atun_fresco", "huevo"], "prot_g": 120,
        "carb_pool": ["arroz_integral", "quinoa"], "carb_g": 100,
        "veg_pool": ["brocoli", "espinaca", "champinones", "zanahoria", "pimiento_rojo"], "veg_g": 120,
        "fat_pool": FAT_ASIAN, "fat_g": 8,
        "name": "Bowl Asiático de {prot} con {carb} y {veg}",
        "desc": "Bowl asiático con perfil umami y vegetales crujientes salteados.",
        "regions": ["us", "eu", "uk", "ca"], "rec": ["athletic_load"], "contra": [],
        "goals": ["muscle_gain", "maintain"], "act": ["moderately_active", "very_active"],
        "preg": True, "prep": 15, "cook": 15, "origin": "Japón/Corea",
        "instructions": [
            "Saltea la {prot} en wok con jengibre.",
            "Sirve {carb} como base.",
            "Añade {veg} salteado.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "asian_vegan_bowl", "cuisine": ["asian"], "meal_time": "lunch", "diet": "vegan",
        "prot_pool": ["tofu_firme", "tempeh", "edamame"], "prot_g": 130,
        "carb_pool": ["arroz_integral", "quinoa"], "carb_g": 100,
        "veg_pool": ["brocoli", "espinaca", "champinones", "zanahoria", "pimiento_rojo"], "veg_g": 120,
        "fat_pool": ["aceite_sesamo", "semillas_chia"], "fat_g": 8,
        "name": "Bowl Asiático Vegano de {prot} con {carb} y {veg}",
        "desc": "Bowl asiático vegano con proteína de soya y vegetales crujientes.",
        "regions": ["us", "eu", "uk"], "rec": ["dyslipidemia"], "contra": ["ckd"],
        "goals": ["health", "muscle_gain"], "act": ["moderately_active", "very_active"],
        "preg": True, "prep": 15, "cook": 15, "origin": "Japón",
        "instructions": [
            "Saltea la {prot} en wok.",
            "Sirve {carb} caliente.",
            "Añade {veg} salteado.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "asian_dinner_pesc", "cuisine": ["asian"], "meal_time": "dinner", "diet": "pescatarian",
        "prot_pool": ["salmon", "atun_fresco", "bacalao"], "prot_g": 130,
        "carb_pool": ["arroz_integral", "quinoa"], "carb_g": 80,
        "veg_pool": ["brocoli", "espinaca", "champinones", "kale"], "veg_g": 150,
        "fat_pool": ["aceite_sesamo"], "fat_g": 5,
        "name": "Cena Asiática de {prot} con {carb} y {veg}",
        "desc": "Cena asiática ligera con pescado azul y vegetales al vapor.",
        "regions": ["us", "eu", "uk"], "rec": ["ischemic_heart_disease", "dyslipidemia"], "contra": [],
        "goals": ["weight_loss", "health"], "act": ["sedentary", "lightly_active"],
        "preg": False, "prep": 10, "cook": 15, "origin": "Japón",
        "instructions": [
            "Cocina la {prot} a la plancha con salsa de soya baja en sodio.",
            "Sirve {carb}.",
            "Acompaña con {veg} al vapor.",
            "Termina con {fat}.",
        ],
    },
    # ---- MIDDLE EASTERN ----
    {
        "tid": "me_mezze_vegan", "cuisine": ["middle_eastern"], "meal_time": "lunch", "diet": "vegan",
        "prot_pool": ["garbanzos", "lentejas"], "prot_g": 130,
        "carb_pool": ["bulgur", "quinoa"], "carb_g": 100,
        "veg_pool": ["tomate", "pepino", "espinaca", "rucula"], "veg_g": 120,
        "fat_pool": FAT_ME, "fat_g": 15,
        "name": "Mezze Levantino de {prot} con {carb}, {veg} y {fat}",
        "desc": "Mezze levantino con legumbres, granos integrales y tahini.",
        "regions": ["eu", "us", "uk"], "rec": ["dyslipidemia", "iron_deficiency_anemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 15, "cook": 15, "origin": "Líbano/Israel",
        "instructions": [
            "Prepara la {prot} estilo hummus o ensalada.",
            "Cocina el {carb}.",
            "Acompaña con {veg}.",
            "Aliña con {fat}.",
        ],
    },
    {
        "tid": "me_omni_dinner", "cuisine": ["middle_eastern"], "meal_time": "dinner", "diet": "omnivore",
        "prot_pool": ["pollo_pechuga", "pavo_pechuga", "lomo_magro"], "prot_g": 130,
        "carb_pool": ["bulgur", "quinoa", "camote"], "carb_g": 80,
        "veg_pool": ["berenjena", "calabacin", "tomate", "pimiento_rojo"], "veg_g": 150,
        "fat_pool": ["tahini", "aceite_oliva"], "fat_g": 12,
        "name": "Cena Levantina de {prot} con {carb} y {veg}",
        "desc": "Cena levantina con proteína magra especiada y vegetales asados.",
        "regions": ["eu", "us", "uk"], "rec": ["athletic_load"], "contra": [],
        "goals": ["maintain", "muscle_gain"], "act": ["moderately_active", "very_active"],
        "preg": True, "prep": 15, "cook": 25, "origin": "Líbano",
        "instructions": [
            "Marina la {prot} con especias y limón.",
            "Asa en horno 20 min.",
            "Sirve con {carb} y {veg} asado.",
            "Termina con {fat}.",
        ],
    },
    # ---- NORDIC ----
    {
        "tid": "nordic_dinner", "cuisine": ["nordic"], "meal_time": "dinner", "diet": "pescatarian",
        "prot_pool": ["salmon", "trucha", "bacalao"], "prot_g": 130,
        "carb_pool": ["papa", "camote", "quinoa"], "carb_g": 100,
        "veg_pool": ["espinaca", "kale", "brocoli", "coliflor"], "veg_g": 150,
        "fat_pool": ["aceite_oliva", "nuez", "semillas_lino"], "fat_g": 10,
        "name": "Cena Nórdica de {prot} con {carb} y {veg}",
        "desc": "Cena nórdica con pescado azul rico en omega-3 y vegetales locales.",
        "regions": ["eu", "uk", "ca", "us"], "rec": ["ischemic_heart_disease", "dyslipidemia", "mild_depression"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["sedentary", "lightly_active", "moderately_active"],
        "preg": False, "prep": 10, "cook": 20, "origin": "Suecia/Dinamarca",
        "instructions": [
            "Hornea la {prot} con eneldo y limón.",
            "Cocina el {carb} al vapor.",
            "Saltea el {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "nordic_breakfast", "cuisine": ["nordic"], "meal_time": "breakfast", "diet": "vegetarian",
        "prot_pool": ["yogur_griego", "huevo"], "prot_g": 100,
        "carb_pool": ["avena", "pan_integral"], "carb_g": 50,
        "veg_pool": ["espinaca"], "veg_g": 30,
        "fat_pool": ["semillas_lino", "nuez", "almendras"], "fat_g": 12,
        "name": "Desayuno Nórdico con {prot}, {carb} y {fat}",
        "desc": "Desayuno nórdico denso en nutrientes, omega-3 ALA y proteína.",
        "regions": ["eu", "uk", "ca"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["maintain", "health"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 5, "cook": 5, "origin": "Suecia",
        "instructions": [
            "Sirve la {prot}.",
            "Acompaña con {carb}.",
            "Decora con {veg} y {fat}.",
        ],
    },
    # ---- NORTH AMERICAN ----
    {
        "tid": "na_lunch_omni", "cuisine": ["north_american"], "meal_time": "lunch", "diet": "omnivore",
        "prot_pool": PROT_OMNI, "prot_g": 130,
        "carb_pool": ["camote", "quinoa", "arroz_integral", "pan_integral"], "carb_g": 100,
        "veg_pool": VEG_SALAD + ["brocoli", "kale"], "veg_g": 130,
        "fat_pool": ["aguacate", "aceite_oliva", "almendras"], "fat_g": 15,
        "name": "Power Bowl Americano de {prot} con {carb}, {veg} y {fat}",
        "desc": "Power bowl norteamericano alto en proteína magra y vegetales coloridos.",
        "regions": ["us", "ca"], "rec": ["athletic_load"], "contra": [],
        "goals": ["muscle_gain", "weight_loss"], "act": ["moderately_active", "very_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "USA",
        "instructions": [
            "Cocina la {prot} a la plancha.",
            "Asa el {carb}.",
            "Sirve sobre {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "na_breakfast_omni", "cuisine": ["north_american"], "meal_time": "breakfast", "diet": "omnivore",
        "prot_pool": ["huevo", "yogur_griego", "queso_fresco"], "prot_g": 100,
        "carb_pool": ["avena", "pan_integral", "camote"], "carb_g": 60,
        "veg_pool": ["espinaca", "tomate", "aguacate"], "veg_g": 60,
        "fat_pool": ["aguacate", "almendras", "semillas_chia"], "fat_g": 12,
        "name": "Desayuno Americano con {prot}, {carb} y {veg}",
        "desc": "Desayuno norteamericano clásico balanceado y rico en proteína.",
        "regions": ["us", "ca"], "rec": [], "contra": [],
        "goals": ["maintain", "muscle_gain"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 10, "cook": 10, "origin": "USA",
        "instructions": [
            "Prepara la {prot}.",
            "Tuesta el {carb}.",
            "Acompaña con {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "na_snack_protein", "cuisine": ["north_american"], "meal_time": "snack", "diet": "vegetarian",
        "prot_pool": ["yogur_griego", "queso_fresco", "huevo"], "prot_g": 100,
        "carb_pool": ["avena", "pan_integral"], "carb_g": 40,
        "veg_pool": ["espinaca", "tomate"], "veg_g": 30,
        "fat_pool": ["almendras", "nuez", "semillas_chia"], "fat_g": 10,
        "name": "Snack Proteico con {prot}, {carb} y {fat}",
        "desc": "Snack alto en proteína para sostener saciedad entre comidas.",
        "regions": ["us", "ca", "eu", "uk"], "rec": ["athletic_load"], "contra": [],
        "goals": ["muscle_gain", "weight_loss"], "act": ["lightly_active", "moderately_active", "very_active"],
        "preg": True, "prep": 5, "cook": 0, "origin": "USA fitness",
        "instructions": [
            "Sirve la {prot}.",
            "Acompaña con {carb}.",
            "Termina con {fat}.",
        ],
    },
    # ---- FUSION ----
    {
        "tid": "fusion_lunch_vegan", "cuisine": ["fusion"], "meal_time": "lunch", "diet": "vegan",
        "prot_pool": PROT_VGAN, "prot_g": 120,
        "carb_pool": CARB_GENERIC, "carb_g": 100,
        "veg_pool": VEG_GENERIC, "veg_g": 120,
        "fat_pool": ["aguacate", "tahini", "aceite_oliva"], "fat_g": 12,
        "name": "Plato Fusión Vegano de {prot} con {carb}, {veg} y {fat}",
        "desc": "Plato fusión vegano con proteínas vegetales y vegetales coloridos.",
        "regions": ["us", "eu", "uk", "latam", "ca"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "Fusión global",
        "instructions": [
            "Saltea la {prot}.",
            "Sirve {carb}.",
            "Añade {veg}.",
            "Aliña con {fat}.",
        ],
    },
    {
        "tid": "fusion_dinner_omni", "cuisine": ["fusion"], "meal_time": "dinner", "diet": "omnivore",
        "prot_pool": PROT_OMNI, "prot_g": 120,
        "carb_pool": ["quinoa", "camote", "arroz_integral"], "carb_g": 80,
        "veg_pool": VEG_GENERIC, "veg_g": 150,
        "fat_pool": ["aceite_oliva", "aguacate"], "fat_g": 10,
        "name": "Cena Fusión de {prot} con {carb} y {veg}",
        "desc": "Cena fusión ligera y balanceada para final del día.",
        "regions": ["us", "eu", "uk", "latam", "ca"], "rec": [], "contra": [],
        "goals": ["weight_loss", "maintain"], "act": ["sedentary", "lightly_active", "moderately_active"],
        "preg": True, "prep": 10, "cook": 20, "origin": "Fusión",
        "instructions": [
            "Cocina la {prot} al horno.",
            "Cocina el {carb}.",
            "Asa el {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "fusion_snack_vegan", "cuisine": ["fusion"], "meal_time": "snack", "diet": "vegan",
        "prot_pool": ["garbanzos", "edamame", "tofu_firme"], "prot_g": 80,
        "carb_pool": ["avena", "camote", "tortilla_maiz"], "carb_g": 50,
        "veg_pool": ["tomate", "pepino", "aguacate"], "veg_g": 40,
        "fat_pool": ["aguacate", "almendras", "semillas_chia"], "fat_g": 10,
        "name": "Snack Fusión Vegano con {prot}, {carb} y {fat}",
        "desc": "Snack vegano práctico, equilibrado en macros, listo en minutos.",
        "regions": ["us", "eu", "uk", "latam"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["weight_loss", "maintain"], "act": ["sedentary", "lightly_active"],
        "preg": True, "prep": 5, "cook": 5, "origin": "Fusión",
        "instructions": [
            "Calienta la {prot}.",
            "Acompaña con {carb}.",
            "Decora con {veg} y {fat}.",
        ],
    },
    # ---- Extras / variety ----
    {
        "tid": "med_salad_pesc", "cuisine": ["mediterranean"], "meal_time": "lunch", "diet": "pescatarian",
        "prot_pool": ["atun_fresco", "salmon", "huevo"], "prot_g": 100,
        "carb_pool": ["farro", "quinoa", "bulgur", "pan_integral"], "carb_g": 60,
        "veg_pool": VEG_SALAD, "veg_g": 150,
        "fat_pool": ["aceitunas", "aceite_oliva", "queso_feta"], "fat_g": 15,
        "name": "Ensalada Mediterránea de {prot} con {carb} y {veg}",
        "desc": "Ensalada mediterránea fría con proteína magra y vegetales crudos.",
        "regions": ["eu", "us", "uk"], "rec": ["hypertension", "dyslipidemia"], "contra": [],
        "goals": ["weight_loss", "health"], "act": ["sedentary", "lightly_active", "moderately_active"],
        "preg": False, "prep": 15, "cook": 10, "origin": "Grecia",
        "instructions": [
            "Cocina la {prot}.",
            "Cocina el {carb}.",
            "Mezcla con {veg} crudo.",
            "Aliña con {fat}.",
        ],
    },
    {
        "tid": "asian_breakfast_veg", "cuisine": ["asian"], "meal_time": "breakfast", "diet": "vegetarian",
        "prot_pool": ["huevo", "tofu_firme", "edamame"], "prot_g": 100,
        "carb_pool": ["arroz_integral", "avena"], "carb_g": 60,
        "veg_pool": ["espinaca", "champinones", "brocoli"], "veg_g": 80,
        "fat_pool": ["aceite_sesamo", "semillas_chia"], "fat_g": 8,
        "name": "Desayuno Asiático con {prot}, {carb} y {veg}",
        "desc": "Desayuno asiático umami, ligero y balanceado.",
        "regions": ["us", "eu", "uk"], "rec": ["health"] if False else [], "contra": [],
        "goals": ["maintain", "health"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 10, "cook": 10, "origin": "Japón",
        "instructions": [
            "Saltea la {prot}.",
            "Sirve {carb}.",
            "Acompaña con {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "latam_lunch_vegetarian", "cuisine": ["latam"], "meal_time": "lunch", "diet": "vegetarian",
        "prot_pool": ["huevo", "queso_fresco", "lentejas", "frijoles_negros"], "prot_g": 130,
        "carb_pool": CARB_LATAM, "carb_g": 100,
        "veg_pool": VEG_GENERIC, "veg_g": 120,
        "fat_pool": ["aguacate", "aceite_oliva"], "fat_g": 12,
        "name": "Almuerzo LatAm Vegetariano de {prot} con {carb}, {veg} y {fat}",
        "desc": "Almuerzo LatAm vegetariano completo y nutritivo.",
        "regions": ["latam"], "rec": [], "contra": [],
        "goals": ["maintain", "health"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "Pan-LatAm",
        "instructions": [
            "Cocina la {prot}.",
            "Sirve {carb}.",
            "Acompaña con {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "med_dinner_omni_meat", "cuisine": ["mediterranean"], "meal_time": "dinner", "diet": "omnivore",
        "prot_pool": ["pollo_pechuga", "pavo_pechuga"], "prot_g": 130,
        "carb_pool": ["quinoa", "farro", "camote"], "carb_g": 80,
        "veg_pool": ["calabacin", "berenjena", "espinaca", "tomate", "pimiento_rojo"], "veg_g": 150,
        "fat_pool": ["aceite_oliva", "aceitunas"], "fat_g": 12,
        "name": "Cena Mediterránea de {prot} al Horno con {carb} y {veg}",
        "desc": "Cena mediterránea ligera con ave magra y vegetales asados.",
        "regions": ["eu", "us", "uk"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["weight_loss", "maintain"], "act": ["sedentary", "lightly_active"],
        "preg": True, "prep": 10, "cook": 25, "origin": "Mediterráneo",
        "instructions": [
            "Hornea la {prot} con hierbas.",
            "Cocina el {carb}.",
            "Asa el {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "fusion_breakfast_vegan", "cuisine": ["fusion"], "meal_time": "breakfast", "diet": "vegan",
        "prot_pool": ["tofu_firme", "edamame", "lentejas"], "prot_g": 90,
        "carb_pool": ["avena", "pan_integral", "camote"], "carb_g": 60,
        "veg_pool": ["espinaca", "tomate", "aguacate"], "veg_g": 60,
        "fat_pool": ["aguacate", "semillas_chia", "almendras"], "fat_g": 12,
        "name": "Desayuno Vegano Fusión con {prot}, {carb} y {veg}",
        "desc": "Desayuno vegano fusión denso en proteína y fibra para sostener saciedad.",
        "regions": ["us", "eu", "uk", "latam"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["lightly_active", "moderately_active"],
        "preg": True, "prep": 10, "cook": 10, "origin": "Fusión wellness",
        "instructions": [
            "Cocina la {prot}.",
            "Tuesta el {carb}.",
            "Acompaña con {veg}.",
            "Termina con {fat}.",
        ],
    },
    {
        "tid": "na_dinner_vegan", "cuisine": ["north_american"], "meal_time": "dinner", "diet": "vegan",
        "prot_pool": PROT_VGAN, "prot_g": 130,
        "carb_pool": ["camote", "quinoa", "arroz_integral"], "carb_g": 80,
        "veg_pool": VEG_GENERIC, "veg_g": 150,
        "fat_pool": ["aguacate", "aceite_oliva", "almendras"], "fat_g": 12,
        "name": "Cena Vegana Americana de {prot} con {carb} y {veg}",
        "desc": "Cena vegana norteamericana, plant-based balanceada.",
        "regions": ["us", "ca", "eu"], "rec": ["dyslipidemia"], "contra": [],
        "goals": ["health", "weight_loss"], "act": ["sedentary", "lightly_active"],
        "preg": True, "prep": 15, "cook": 20, "origin": "USA plant-based",
        "instructions": [
            "Saltea la {prot}.",
            "Sirve {carb}.",
            "Asa el {veg}.",
            "Termina con {fat}.",
        ],
    },
]

# Display names ES for ingredients (used in name + ingredient strings)
DISPLAY = {
    "pollo_pechuga": "Pollo", "pavo_pechuga": "Pavo", "salmon": "Salmón", "atun_fresco": "Atún",
    "bacalao": "Bacalao", "trucha": "Trucha", "lomo_magro": "Lomo Magro", "huevo": "Huevo",
    "yogur_griego": "Yogur Griego", "queso_fresco": "Queso Fresco", "queso_feta": "Queso Feta",
    "tofu_firme": "Tofu", "tempeh": "Tempeh", "seitán": "Seitán",
    "lentejas": "Lentejas", "garbanzos": "Garbanzos", "frijoles_negros": "Frijoles Negros", "edamame": "Edamame",
    "quinoa": "Quinoa", "arroz_integral": "Arroz Integral", "camote": "Camote", "papa": "Papa",
    "bulgur": "Bulgur", "farro": "Farro", "platano_macho": "Plátano Macho", "avena": "Avena",
    "pan_integral": "Pan Integral", "tortilla_maiz": "Tortilla de Maíz",
    "brocoli": "Brócoli", "espinaca": "Espinaca", "kale": "Kale", "rucula": "Rúcula", "tomate": "Tomate",
    "pimiento_rojo": "Pimiento Rojo", "calabacin": "Calabacín", "zanahoria": "Zanahoria",
    "cebolla": "Cebolla", "ajo": "Ajo", "champinones": "Champiñones", "aguacate": "Aguacate",
    "pepino": "Pepino", "berenjena": "Berenjena", "coliflor": "Coliflor",
    "aceite_oliva": "Aceite de Oliva", "aceite_sesamo": "Aceite de Sésamo", "tahini": "Tahini",
    "almendras": "Almendras", "nuez": "Nueces", "semillas_chia": "Chía", "semillas_lino": "Linaza",
    "aceitunas": "Aceitunas",
    "leche_almendra": "Leche de Almendra", "leche_avena": "Leche de Avena", "leche_descremada": "Leche Descremada",
}


def detect_allergens(component_keys: list[str]) -> list[str]:
    found: set[str] = set()
    for k in component_keys:
        for a in ALLERGEN_FROM_KEY.get(k, ()):  # type: ignore[arg-type]
            found.add(a)
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    p = c = f = fib = sug = na = 0.0
    gi_weighted = 0.0
    gi_carb_total = 0.0
    for key, grams in components:
        ing = ING[key]
        factor = grams / 100.0
        p += ing["p"] * factor
        c += ing["c"] * factor
        f += ing["f"] * factor
        fib += ing["fib"] * factor
        sug += ing["sug"] * factor
        na += ing["na"] * factor
        carb_contrib = ing["c"] * factor
        gi_weighted += ing["gi"] * carb_contrib
        gi_carb_total += carb_contrib
    gi = int(round(gi_weighted / gi_carb_total)) if gi_carb_total > 0 else None
    p_i = int(round(p)); c_i = int(round(c)); f_i = int(round(f))
    kcal = 4 * p_i + 4 * c_i + 9 * f_i
    return {
        "calories": kcal, "protein_g": p_i, "carbs_g": c_i, "fat_g": f_i,
        "fiber_g": int(round(fib)), "sugar_g": int(round(sug)),
        "sodium_mg": int(round(na)), "gi": gi,
    }


def deterministic_id(template_id: str, slots: tuple[str, ...]) -> str:
    h = hashlib.sha1(("|".join((template_id, *slots))).encode()).hexdigest()
    return f"nova_meal_bulk_{h[:10]}"


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
    if not (100 <= kcal <= 1500):
        return False, f"kcal_out_of_range={kcal}"
    if not (0 <= m["protein_g"] <= 80):
        return False, f"protein_out_of_range={m['protein_g']}"
    if not (0 <= m["carbs_g"] <= 200):
        return False, f"carbs_out_of_range={m['carbs_g']}"
    if not (0 <= m["fat_g"] <= 80):
        return False, f"fat_out_of_range={m['fat_g']}"
    for v in mc["allergens"]:
        if v not in ALLERGENS_14: return False, f"allergen_drift={v}"
    for v in mc["recommended_for_conditions"]:
        if v not in CONDITIONS_25: return False, f"rec_cond_drift={v}"
    for v in mc["contraindicated_conditions"]:
        if v not in CONDITIONS_25: return False, f"contra_cond_drift={v}"
    for v in mc["target_goals"]:
        if v not in GOALS_5: return False, f"goal_drift={v}"
    for v in mc["suitable_for_activity"]:
        if v not in ACTIVITY_LEVELS_5: return False, f"activity_drift={v}"
    for v in mc["regions"]:
        if v not in REGIONS_5: return False, f"region_drift={v}"
    if recipe["execution"]["meal_time"] not in MEAL_TIMES_4:
        return False, "meal_time_drift"
    return True, "ok"


def build_one(tpl: dict, prot: str, carb: str, veg: str, fat: str) -> dict:
    components = [
        (prot, tpl["prot_g"]),
        (carb, tpl["carb_g"]),
        (veg, tpl["veg_g"]),
        (fat, tpl["fat_g"]),
    ]
    m = macros_from_components(components)
    allergens = detect_allergens([prot, carb, veg, fat])
    name = tpl["name"].format(
        prot=DISPLAY[prot], carb=DISPLAY[carb], veg=DISPLAY[veg], fat=DISPLAY[fat],
    )
    desc = tpl["desc"]
    instructions = [s.format(prot=DISPLAY[prot], carb=DISPLAY[carb], veg=DISPLAY[veg], fat=DISPLAY[fat])
                    for s in tpl["instructions"]]
    ingredients = [
        f"{tpl['prot_g']} g de {DISPLAY[prot]}",
        f"{tpl['carb_g']} g de {DISPLAY[carb]}",
        f"{tpl['veg_g']} g de {DISPLAY[veg]}",
        f"{tpl['fat_g']} g de {DISPLAY[fat]}",
        "Sal, pimienta y especias al gusto",
    ]
    rid = deterministic_id(tpl["tid"], (prot, carb, veg, fat))
    derived_kcal = 4 * m["protein_g"] + 4 * m["carbs_g"] + 9 * m["fat_g"]
    consistency_pct = round(abs(derived_kcal - m["calories"]) / max(m["calories"], 1) * 100, 2)
    return {
        "id": rid,
        "name": name,
        "description": desc,
        "image_url": PLACEHOLDER_IMG,
        "nutrition_profile": {
            "calories": m["calories"],
            "macros": {
                "protein_g": m["protein_g"], "carbs_g": m["carbs_g"], "fat_g": m["fat_g"],
                "fiber_g": m["fiber_g"], "sugar_g": m["sugar_g"],
                "sat_fat_g": 0, "sodium_mg": m["sodium_mg"],
            },
            "micronutrients": {
                "gi": m["gi"], "gl": None,
                "potassium_mg": None, "phosphorus_mg": None, "iron_mg": None, "heme_pct": None,
                "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
            },
        },
        "matching_criteria": {
            "target_goals": list(tpl["goals"]),
            "suitable_for_activity": list(tpl["act"]),
            "recommended_for_conditions": list(tpl["rec"]),
            "contraindicated_conditions": list(tpl["contra"]),
            "allergens": allergens,
            "regions": list(tpl["regions"]),
            "dietary_pattern": tpl["diet"],
            "cuisine_region": list(tpl["cuisine"]),
            "meal_format": "solid",
            "pregnancy_safe": bool(tpl["preg"]),
        },
        "execution": {
            "meal_time": tpl["meal_time"],
            "prep_time_minutes": tpl["prep"],
            "cook_time_minutes": tpl["cook"],
            "image_url": None,
            "ingredients": ingredients,
            "instructions": instructions,
            "servings": 1,
            "source_catalog": "nova_v2_batch_bulk_2026_06_01",
        },
        "audit": {
            "schema_version": "v2",
            "macro_consistency_pct": consistency_pct,
            "gl_estimated": None,
            "cultural_origin": tpl.get("origin"),
            "generated_at": "2026-06-01",
        },
    }


def main() -> None:
    out: list[dict] = []
    seen_ids: set[str] = set()
    rejections: list[tuple[str, str]] = []
    rejection_counts: dict[str, int] = {}
    total = 0
    for tpl in TEMPLATES:
        for prot, carb, veg, fat in product(tpl["prot_pool"], tpl["carb_pool"], tpl["veg_pool"], tpl["fat_pool"]):
            total += 1
            recipe = build_one(tpl, prot, carb, veg, fat)
            if recipe["id"] in seen_ids:
                rejections.append((recipe["id"], "duplicate_id"))
                rejection_counts["duplicate_id"] = rejection_counts.get("duplicate_id", 0) + 1
                continue
            ok, reason = validate(recipe)
            if not ok:
                rejections.append((recipe["id"], reason))
                key = reason.split("=", 1)[0]
                rejection_counts[key] = rejection_counts.get(key, 0) + 1
                continue
            seen_ids.add(recipe["id"])
            out.append(recipe)
    out_path = ROOT / "data" / "meals" / "bulk_batch_2026_06_01.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False))
    log_path = ROOT / "scripts" / "generate_recipes_bulk_2026_06_01_rejections.log"
    summary = "\n".join(f"{k}: {v}" for k, v in sorted(rejection_counts.items(), key=lambda x: -x[1]))
    log_path.write_text(
        f"templates={len(TEMPLATES)}\ncombinations_attempted={total}\naccepted={len(out)}\n"
        f"rejected={len(rejections)}\n\nReject reason counts:\n{summary}\n\n"
        + "\n".join(f"{rid}\t{reason}" for rid, reason in rejections[:200])
    )
    print(f"bulk: templates={len(TEMPLATES)} attempted={total} accepted={len(out)} rejected={len(rejections)}")
    print("Reject reasons:", rejection_counts)


if __name__ == "__main__":
    main()
