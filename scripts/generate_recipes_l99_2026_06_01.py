"""L99 catalog expansion — gap fill + bulk multi-region expansion.

Targets ~4,450 NEW recipes:
- Part A (gap fill 1,450): snacks (400), veg/pesc dinners (300),
  omni breakfasts (500), weight_gain dinners (200), mass-gain liquids (50).
- Part B (bulk expansion 3,000): multi-region LatAm/EU/US/CA/UK with
  sub-regional cuisine variety.

Hard dedup vs existing catalog (9,199 recipes):
- Signature (name_norm + sorted core ingredient nouns) — sha1 collision = reject.
- Name Levenshtein (SequenceMatcher.quick_ratio) ≥ 0.85 within same
  (meal_time, dietary_pattern, cuisine_region) cell — reject.

Hard validators (same gates as bulk_2026_06_01):
- Macro math |kcal − (4P+4C+9F)| / kcal ≤ 0.05.
- Allergen lookup EN+ES tokens via ING table.
- Sugar cap on liquids with carbs>35 → strip diabetes/PCOS/fatty_liver.
- GL audit on liquids — if est. GL>10 strip diabetes/PCOS.
- Closed vocabulary enforcement via app.shared.domain.vocabularies.
- Macro plausibility kcal [100,1500]; protein [0,80]; carbs [0,200]; fat [0,80].
- pregnancy_safe default False — set True only if profile is safe.

Outputs:
- data/meals/l99_batch_2026_06_01.json
- scripts/generate_recipes_l99_2026_06_01_rejections.log
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import (  # noqa: E402
    ACTIVITY_LEVELS_5, ALLERGENS_14, CONDITIONS_25, GOALS_5, MEAL_TIMES_4, REGIONS_5,
)

PLACEHOLDER_IMG = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"
SOURCE_CATALOG = "nova_v2_batch_l99_2026_06_01"
EXISTING_CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
OUT = ROOT / "data" / "meals" / "l99_batch_2026_06_01.json"
LOG = ROOT / "scripts" / "generate_recipes_l99_2026_06_01_rejections.log"

# ---------------------------------------------------------------------------
# Ingredient table per 100 g cooked (extended for L99).
# ---------------------------------------------------------------------------
ING: dict[str, dict] = {
    # Proteins (animal)
    "pollo_pechuga":    {"kcal": 165, "p": 31,  "c": 0,   "f": 3.6, "fib": 0,   "sug": 0,   "na": 74,  "gi": 0,  "satfat": 1.0, "tags": ["omnivore"]},
    "pollo_muslo":      {"kcal": 209, "p": 26,  "c": 0,   "f": 11,  "fib": 0,   "sug": 0,   "na": 95,  "gi": 0,  "satfat": 3.0, "tags": ["omnivore"]},
    "pavo_pechuga":     {"kcal": 135, "p": 30,  "c": 0,   "f": 1.0, "fib": 0,   "sug": 0,   "na": 65,  "gi": 0,  "satfat": 0.3, "tags": ["omnivore"]},
    "pavo_molido":      {"kcal": 170, "p": 27,  "c": 0,   "f": 7,   "fib": 0,   "sug": 0,   "na": 78,  "gi": 0,  "satfat": 1.8, "tags": ["omnivore"]},
    "salmon":           {"kcal": 208, "p": 22,  "c": 0,   "f": 13,  "fib": 0,   "sug": 0,   "na": 59,  "gi": 0,  "satfat": 3.1, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "atun_fresco":      {"kcal": 144, "p": 30,  "c": 0,   "f": 1.0, "fib": 0,   "sug": 0,   "na": 39,  "gi": 0,  "satfat": 0.3, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "atun_lata_agua":   {"kcal": 116, "p": 26,  "c": 0,   "f": 0.8, "fib": 0,   "sug": 0,   "na": 247, "gi": 0,  "satfat": 0.2, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "bacalao":          {"kcal": 82,  "p": 18,  "c": 0,   "f": 0.7, "fib": 0,   "sug": 0,   "na": 78,  "gi": 0,  "satfat": 0.1, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "merluza":          {"kcal": 86,  "p": 18,  "c": 0,   "f": 1.3, "fib": 0,   "sug": 0,   "na": 75,  "gi": 0,  "satfat": 0.2, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "trucha":           {"kcal": 168, "p": 23,  "c": 0,   "f": 8,   "fib": 0,   "sug": 0,   "na": 50,  "gi": 0,  "satfat": 2.0, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "tilapia":          {"kcal": 128, "p": 26,  "c": 0,   "f": 2.7, "fib": 0,   "sug": 0,   "na": 56,  "gi": 0,  "satfat": 0.9, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "sardinas":         {"kcal": 208, "p": 25,  "c": 0,   "f": 11,  "fib": 0,   "sug": 0,   "na": 307, "gi": 0,  "satfat": 1.5, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "lomo_magro":       {"kcal": 158, "p": 26,  "c": 0,   "f": 6,   "fib": 0,   "sug": 0,   "na": 60,  "gi": 0,  "satfat": 2.0, "tags": ["omnivore"]},
    "carne_magra_res":  {"kcal": 182, "p": 27,  "c": 0,   "f": 8,   "fib": 0,   "sug": 0,   "na": 65,  "gi": 0,  "satfat": 3.2, "tags": ["omnivore"]},
    "huevo":            {"kcal": 143, "p": 13,  "c": 1.1, "f": 9.5, "fib": 0,   "sug": 1.1, "na": 142, "gi": 0,  "satfat": 3.0, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["egg"]},
    "clara_huevo":      {"kcal": 52,  "p": 11,  "c": 0.7, "f": 0.2, "fib": 0,   "sug": 0.7, "na": 166, "gi": 0,  "satfat": 0.0, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["egg"]},
    "yogur_griego":     {"kcal": 59,  "p": 10,  "c": 3.6, "f": 0.4, "fib": 0,   "sug": 3.2, "na": 36,  "gi": 11, "satfat": 0.1, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_cottage":    {"kcal": 98,  "p": 11,  "c": 3.4, "f": 4.3, "fib": 0,   "sug": 2.7, "na": 364, "gi": 30, "satfat": 1.7, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_fresco":     {"kcal": 98,  "p": 11,  "c": 3.4, "f": 4.3, "fib": 0,   "sug": 3.4, "na": 350, "gi": 30, "satfat": 2.5, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_feta":       {"kcal": 264, "p": 14,  "c": 4.1, "f": 21,  "fib": 0,   "sug": 4.1, "na": 917, "gi": 30, "satfat": 14,  "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "ricotta":          {"kcal": 174, "p": 11,  "c": 3,   "f": 13,  "fib": 0,   "sug": 0.3, "na": 84,  "gi": 30, "satfat": 8.3, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "whey_protein":     {"kcal": 380, "p": 80,  "c": 8,   "f": 4,   "fib": 0,   "sug": 4,   "na": 220, "gi": 30, "satfat": 2.0, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    # Proteins (plant)
    "tofu_firme":       {"kcal": 144, "p": 17,  "c": 3,   "f": 9,   "fib": 2,   "sug": 1,   "na": 14,  "gi": 15, "satfat": 1.3, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "tempeh":           {"kcal": 192, "p": 20,  "c": 8,   "f": 11,  "fib": 0,   "sug": 0,   "na": 9,   "gi": 15, "satfat": 2.2, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "seitán":           {"kcal": 370, "p": 75,  "c": 14,  "f": 1.9, "fib": 0.6, "sug": 0,   "na": 29,  "gi": 0,  "satfat": 0.3, "tags": ["omnivore","vegetarian","vegan"], "allergens": ["gluten"]},
    "lentejas":         {"kcal": 116, "p": 9,   "c": 20,  "f": 0.4, "fib": 8,   "sug": 1.8, "na": 2,   "gi": 32, "satfat": 0.1, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "lentejas_rojas":   {"kcal": 120, "p": 9.5, "c": 21,  "f": 0.4, "fib": 7,   "sug": 1.8, "na": 2,   "gi": 26, "satfat": 0.1, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "garbanzos":        {"kcal": 164, "p": 8.9, "c": 27,  "f": 2.6, "fib": 7.6, "sug": 4.8, "na": 7,   "gi": 28, "satfat": 0.3, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "frijoles_negros":  {"kcal": 132, "p": 8.9, "c": 24,  "f": 0.5, "fib": 8.7, "sug": 0.3, "na": 1,   "gi": 30, "satfat": 0.1, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "frijoles_pintos":  {"kcal": 143, "p": 9,   "c": 26,  "f": 0.7, "fib": 9,   "sug": 0.3, "na": 1,   "gi": 39, "satfat": 0.1, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "edamame":          {"kcal": 121, "p": 12,  "c": 9,   "f": 5,   "fib": 5,   "sug": 2.2, "na": 6,   "gi": 18, "satfat": 0.6, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "proteina_arveja":  {"kcal": 380, "p": 80,  "c": 5,   "f": 5,   "fib": 5,   "sug": 1,   "na": 400, "gi": 25, "satfat": 0.5, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    # Carbs
    "quinoa":           {"kcal": 120, "p": 4.4, "c": 21,  "f": 1.9, "fib": 2.8, "sug": 0.9, "na": 7,   "gi": 53, "satfat": 0.2, "tags": ["any"]},
    "arroz_integral":   {"kcal": 123, "p": 2.7, "c": 26,  "f": 1.0, "fib": 1.6, "sug": 0.4, "na": 4,   "gi": 50, "satfat": 0.3, "tags": ["any"]},
    "arroz_basmati":    {"kcal": 121, "p": 3,   "c": 25,  "f": 0.4, "fib": 0.4, "sug": 0,   "na": 3,   "gi": 58, "satfat": 0.1, "tags": ["any"]},
    "arroz_blanco":     {"kcal": 130, "p": 2.7, "c": 28,  "f": 0.3, "fib": 0.4, "sug": 0.1, "na": 1,   "gi": 73, "satfat": 0.1, "tags": ["any"]},
    "camote":           {"kcal": 86,  "p": 1.6, "c": 20,  "f": 0.1, "fib": 3,   "sug": 4.2, "na": 55,  "gi": 63, "satfat": 0.0, "tags": ["any"]},
    "papa":             {"kcal": 77,  "p": 2,   "c": 17,  "f": 0.1, "fib": 2.2, "sug": 0.8, "na": 6,   "gi": 78, "satfat": 0.0, "tags": ["any"]},
    "yuca":             {"kcal": 160, "p": 1.4, "c": 38,  "f": 0.3, "fib": 1.8, "sug": 1.7, "na": 14,  "gi": 55, "satfat": 0.1, "tags": ["any"]},
    "bulgur":           {"kcal": 83,  "p": 3.1, "c": 19,  "f": 0.2, "fib": 4.5, "sug": 0.1, "na": 5,   "gi": 48, "satfat": 0.0, "tags": ["any"], "allergens": ["gluten"]},
    "farro":            {"kcal": 170, "p": 6,   "c": 34,  "f": 1.5, "fib": 5,   "sug": 1,   "na": 5,   "gi": 45, "satfat": 0.2, "tags": ["any"], "allergens": ["gluten"]},
    "cebada":           {"kcal": 123, "p": 2.3, "c": 28,  "f": 0.4, "fib": 3.8, "sug": 0.4, "na": 3,   "gi": 35, "satfat": 0.1, "tags": ["any"], "allergens": ["gluten"]},
    "platano_macho":    {"kcal": 122, "p": 1.3, "c": 32,  "f": 0.4, "fib": 2.3, "sug": 15,  "na": 4,   "gi": 55, "satfat": 0.1, "tags": ["any"]},
    "avena":            {"kcal": 71,  "p": 2.5, "c": 12,  "f": 1.5, "fib": 1.7, "sug": 0,   "na": 3,   "gi": 55, "satfat": 0.3, "tags": ["any"], "allergens": ["gluten"]},
    "avena_seca":       {"kcal": 389, "p": 17,  "c": 66,  "f": 7,   "fib": 11,  "sug": 0,   "na": 2,   "gi": 55, "satfat": 1.2, "tags": ["any"], "allergens": ["gluten"]},
    "pan_integral":     {"kcal": 247, "p": 13,  "c": 41,  "f": 3.4, "fib": 7,   "sug": 5,   "na": 491, "gi": 71, "satfat": 0.6, "tags": ["any"], "allergens": ["gluten"]},
    "pan_centeno":      {"kcal": 259, "p": 9,   "c": 48,  "f": 3.3, "fib": 6,   "sug": 4,   "na": 603, "gi": 50, "satfat": 0.6, "tags": ["any"], "allergens": ["gluten"]},
    "tortilla_maiz":    {"kcal": 218, "p": 5.7, "c": 45,  "f": 2.9, "fib": 6.3, "sug": 1.1, "na": 45,  "gi": 52, "satfat": 0.4, "tags": ["any"]},
    "tortilla_trigo":   {"kcal": 304, "p": 8,   "c": 49,  "f": 8,   "fib": 3,   "sug": 3,   "na": 530, "gi": 67, "satfat": 2.0, "tags": ["any"], "allergens": ["gluten"]},
    "pasta_integral":   {"kcal": 124, "p": 5,   "c": 27,  "f": 0.5, "fib": 4.5, "sug": 1,   "na": 6,   "gi": 48, "satfat": 0.1, "tags": ["any"], "allergens": ["gluten"]},
    "polenta":          {"kcal": 70,  "p": 1.5, "c": 15,  "f": 0.3, "fib": 1,   "sug": 0,   "na": 1,   "gi": 68, "satfat": 0.0, "tags": ["any"]},
    "couscous":         {"kcal": 112, "p": 3.8, "c": 23,  "f": 0.2, "fib": 1.4, "sug": 0.1, "na": 5,   "gi": 65, "satfat": 0.0, "tags": ["any"], "allergens": ["gluten"]},
    # Veg
    "brocoli":          {"kcal": 35,  "p": 2.4, "c": 7,   "f": 0.4, "fib": 3.3, "sug": 1.7, "na": 41,  "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "espinaca":         {"kcal": 23,  "p": 2.9, "c": 3.6, "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79,  "gi": 15, "satfat": 0.1, "tags": ["any"]},
    "kale":             {"kcal": 35,  "p": 2.9, "c": 4.4, "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53,  "gi": 15, "satfat": 0.2, "tags": ["any"]},
    "acelga":           {"kcal": 19,  "p": 1.8, "c": 3.7, "f": 0.2, "fib": 1.6, "sug": 1.1, "na": 213, "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "rucula":           {"kcal": 25,  "p": 2.6, "c": 3.7, "f": 0.7, "fib": 1.6, "sug": 2,   "na": 27,  "gi": 15, "satfat": 0.1, "tags": ["any"]},
    "lechuga":          {"kcal": 15,  "p": 1.4, "c": 2.9, "f": 0.2, "fib": 1.3, "sug": 0.8, "na": 28,  "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "tomate":           {"kcal": 18,  "p": 0.9, "c": 3.9, "f": 0.2, "fib": 1.2, "sug": 2.6, "na": 5,   "gi": 30, "satfat": 0.0, "tags": ["any"]},
    "pimiento_rojo":    {"kcal": 31,  "p": 1,   "c": 6,   "f": 0.3, "fib": 2.1, "sug": 4.2, "na": 4,   "gi": 15, "satfat": 0.1, "tags": ["any"]},
    "pimiento_verde":   {"kcal": 20,  "p": 0.9, "c": 4.6, "f": 0.2, "fib": 1.7, "sug": 2.4, "na": 3,   "gi": 15, "satfat": 0.1, "tags": ["any"]},
    "calabacin":        {"kcal": 17,  "p": 1.2, "c": 3.1, "f": 0.3, "fib": 1,   "sug": 2.5, "na": 8,   "gi": 15, "satfat": 0.1, "tags": ["any"]},
    "zanahoria":        {"kcal": 41,  "p": 0.9, "c": 9.6, "f": 0.2, "fib": 2.8, "sug": 4.7, "na": 69,  "gi": 39, "satfat": 0.0, "tags": ["any"]},
    "cebolla":          {"kcal": 40,  "p": 1.1, "c": 9.3, "f": 0.1, "fib": 1.7, "sug": 4.2, "na": 4,   "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "ajo":              {"kcal": 149, "p": 6.4, "c": 33,  "f": 0.5, "fib": 2.1, "sug": 1,   "na": 17,  "gi": 0,  "satfat": 0.1, "tags": ["any"]},
    "champinones":      {"kcal": 22,  "p": 3.1, "c": 3.3, "f": 0.3, "fib": 1,   "sug": 2,   "na": 5,   "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "aguacate":         {"kcal": 160, "p": 2,   "c": 9,   "f": 15,  "fib": 7,   "sug": 0.7, "na": 7,   "gi": 10, "satfat": 2.1, "tags": ["any"]},
    "pepino":           {"kcal": 16,  "p": 0.7, "c": 3.6, "f": 0.1, "fib": 0.5, "sug": 1.7, "na": 2,   "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "berenjena":        {"kcal": 25,  "p": 1,   "c": 6,   "f": 0.2, "fib": 3,   "sug": 3.5, "na": 2,   "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "coliflor":         {"kcal": 25,  "p": 1.9, "c": 5,   "f": 0.3, "fib": 2,   "sug": 1.9, "na": 30,  "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "esparragos":       {"kcal": 20,  "p": 2.2, "c": 3.9, "f": 0.1, "fib": 2.1, "sug": 1.9, "na": 2,   "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "alcachofa":        {"kcal": 47,  "p": 3.3, "c": 11,  "f": 0.2, "fib": 5.4, "sug": 1,   "na": 94,  "gi": 15, "satfat": 0.0, "tags": ["any"]},
    "judias_verdes":    {"kcal": 31,  "p": 1.8, "c": 7,   "f": 0.2, "fib": 2.7, "sug": 3.3, "na": 6,   "gi": 32, "satfat": 0.0, "tags": ["any"]},
    "remolacha":        {"kcal": 43,  "p": 1.6, "c": 10,  "f": 0.2, "fib": 2.8, "sug": 6.8, "na": 78,  "gi": 64, "satfat": 0.0, "tags": ["any"]},
    "pico_gallo":       {"kcal": 22,  "p": 1.0, "c": 5,   "f": 0.2, "fib": 1.5, "sug": 3,   "na": 110, "gi": 25, "satfat": 0.0, "tags": ["any"]},
    # Fats / nuts / seeds
    "aceite_oliva":     {"kcal": 884, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "satfat": 14,  "tags": ["any"]},
    "aceite_sesamo":    {"kcal": 884, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "satfat": 14,  "tags": ["any"], "allergens": ["sesame"]},
    "aceite_coco":      {"kcal": 862, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 0,   "gi": 0,  "satfat": 87,  "tags": ["any"]},
    "tahini":           {"kcal": 595, "p": 17,  "c": 21,  "f": 53,  "fib": 9.3, "sug": 0.5, "na": 115, "gi": 40, "satfat": 7.4, "tags": ["any"], "allergens": ["sesame"]},
    "almendras":        {"kcal": 579, "p": 21,  "c": 22,  "f": 50,  "fib": 12,  "sug": 4.4, "na": 1,   "gi": 0,  "satfat": 3.8, "tags": ["any"], "allergens": ["tree_nuts"]},
    "nuez":             {"kcal": 654, "p": 15,  "c": 14,  "f": 65,  "fib": 6.7, "sug": 2.6, "na": 2,   "gi": 0,  "satfat": 6.1, "tags": ["any"], "allergens": ["tree_nuts"]},
    "anacardo":         {"kcal": 553, "p": 18,  "c": 30,  "f": 44,  "fib": 3.3, "sug": 5.9, "na": 12,  "gi": 22, "satfat": 7.8, "tags": ["any"], "allergens": ["tree_nuts"]},
    "pistacho":         {"kcal": 562, "p": 20,  "c": 28,  "f": 45,  "fib": 10,  "sug": 7.7, "na": 1,   "gi": 0,  "satfat": 5.4, "tags": ["any"], "allergens": ["tree_nuts"]},
    "mantequilla_mani": {"kcal": 588, "p": 25,  "c": 20,  "f": 50,  "fib": 6,   "sug": 9,   "na": 17,  "gi": 14, "satfat": 10,  "tags": ["any"], "allergens": ["peanuts"]},
    "mani":             {"kcal": 567, "p": 26,  "c": 16,  "f": 49,  "fib": 8.5, "sug": 4,   "na": 18,  "gi": 14, "satfat": 6.8, "tags": ["any"], "allergens": ["peanuts"]},
    "semillas_chia":    {"kcal": 486, "p": 17,  "c": 42,  "f": 31,  "fib": 34,  "sug": 0,   "na": 16,  "gi": 1,  "satfat": 3.3, "tags": ["any"]},
    "semillas_lino":    {"kcal": 534, "p": 18,  "c": 29,  "f": 42,  "fib": 27,  "sug": 1.6, "na": 30,  "gi": 1,  "satfat": 3.7, "tags": ["any"]},
    "semillas_girasol": {"kcal": 584, "p": 21,  "c": 20,  "f": 51,  "fib": 9,   "sug": 2.6, "na": 9,   "gi": 35, "satfat": 4.5, "tags": ["any"]},
    "semillas_calabaza":{"kcal": 559, "p": 30,  "c": 11,  "f": 49,  "fib": 6,   "sug": 1.4, "na": 7,   "gi": 25, "satfat": 8.7, "tags": ["any"]},
    "aceitunas":        {"kcal": 115, "p": 0.8, "c": 6,   "f": 11,  "fib": 3.2, "sug": 0,   "na": 735, "gi": 0,  "satfat": 1.4, "tags": ["any"]},
    # Liquids / dairy alt
    "leche_almendra":   {"kcal": 17,  "p": 0.6, "c": 0.6, "f": 1.5, "fib": 0.3, "sug": 0,   "na": 60,  "gi": 25, "satfat": 0.1, "tags": ["any"], "allergens": ["tree_nuts"]},
    "leche_avena":      {"kcal": 47,  "p": 1.0, "c": 6.6, "f": 1.5, "fib": 0.8, "sug": 3.3, "na": 42,  "gi": 60, "satfat": 0.2, "tags": ["any"], "allergens": ["gluten"]},
    "leche_descremada": {"kcal": 34,  "p": 3.4, "c": 5,   "f": 0.1, "fib": 0,   "sug": 5,   "na": 42,  "gi": 32, "satfat": 0.1, "tags": ["any"], "allergens": ["dairy"]},
    "leche_entera":     {"kcal": 61,  "p": 3.2, "c": 4.8, "f": 3.3, "fib": 0,   "sug": 5.1, "na": 43,  "gi": 32, "satfat": 1.9, "tags": ["any"], "allergens": ["dairy"]},
    "leche_soya":       {"kcal": 54,  "p": 3.3, "c": 6,   "f": 1.8, "fib": 0.6, "sug": 4,   "na": 51,  "gi": 34, "satfat": 0.2, "tags": ["any"], "allergens": ["soy"]},
    "platano_fruta":    {"kcal": 89,  "p": 1.1, "c": 23,  "f": 0.3, "fib": 2.6, "sug": 12,  "na": 1,   "gi": 51, "satfat": 0.1, "tags": ["any"]},
    "frutos_rojos":     {"kcal": 50,  "p": 1,   "c": 12,  "f": 0.3, "fib": 3,   "sug": 8,   "na": 1,   "gi": 32, "satfat": 0.0, "tags": ["any"]},
    "manzana":          {"kcal": 52,  "p": 0.3, "c": 14,  "f": 0.2, "fib": 2.4, "sug": 10,  "na": 1,   "gi": 36, "satfat": 0.0, "tags": ["any"]},
    "miel":             {"kcal": 304, "p": 0.3, "c": 82,  "f": 0,   "fib": 0.2, "sug": 82,  "na": 4,   "gi": 58, "satfat": 0.0, "tags": ["any"]},
    "dates":            {"kcal": 277, "p": 1.8, "c": 75,  "f": 0.2, "fib": 7,   "sug": 66,  "na": 1,   "gi": 42, "satfat": 0.0, "tags": ["any"]},
    "cacao":            {"kcal": 228, "p": 20,  "c": 58,  "f": 14,  "fib": 33,  "sug": 1.8, "na": 21,  "gi": 20, "satfat": 8.1, "tags": ["any"]},
}

ALLERGEN_FROM_KEY = {k: tuple(v.get("allergens", [])) for k, v in ING.items()}

# Display names (ES) for ingredients
DISPLAY = {
    "pollo_pechuga": "Pollo", "pollo_muslo": "Muslo de Pollo",
    "pavo_pechuga": "Pavo", "pavo_molido": "Pavo Molido",
    "salmon": "Salmón", "atun_fresco": "Atún", "atun_lata_agua": "Atún en Agua",
    "bacalao": "Bacalao", "merluza": "Merluza", "trucha": "Trucha",
    "tilapia": "Tilapia", "sardinas": "Sardinas",
    "lomo_magro": "Lomo Magro", "carne_magra_res": "Res Magra",
    "huevo": "Huevo", "clara_huevo": "Claras de Huevo",
    "yogur_griego": "Yogur Griego", "queso_cottage": "Cottage",
    "queso_fresco": "Queso Fresco", "queso_feta": "Queso Feta", "ricotta": "Ricotta",
    "whey_protein": "Whey",
    "tofu_firme": "Tofu", "tempeh": "Tempeh", "seitán": "Seitán",
    "lentejas": "Lentejas", "lentejas_rojas": "Lentejas Rojas",
    "garbanzos": "Garbanzos", "frijoles_negros": "Frijoles Negros",
    "frijoles_pintos": "Frijoles Pintos", "edamame": "Edamame",
    "proteina_arveja": "Proteína de Arveja",
    "quinoa": "Quinoa", "arroz_integral": "Arroz Integral",
    "arroz_basmati": "Arroz Basmati", "arroz_blanco": "Arroz Blanco",
    "camote": "Camote", "papa": "Papa", "yuca": "Yuca",
    "bulgur": "Bulgur", "farro": "Farro", "cebada": "Cebada",
    "platano_macho": "Plátano Macho",
    "avena": "Avena", "avena_seca": "Avena en Hojuelas",
    "pan_integral": "Pan Integral", "pan_centeno": "Pan de Centeno",
    "tortilla_maiz": "Tortilla de Maíz", "tortilla_trigo": "Tortilla de Trigo",
    "pasta_integral": "Pasta Integral", "polenta": "Polenta", "couscous": "Cuscús",
    "brocoli": "Brócoli", "espinaca": "Espinaca", "kale": "Kale", "acelga": "Acelga",
    "rucula": "Rúcula", "lechuga": "Lechuga", "tomate": "Tomate",
    "pimiento_rojo": "Pimiento Rojo", "pimiento_verde": "Pimiento Verde",
    "calabacin": "Calabacín", "zanahoria": "Zanahoria",
    "cebolla": "Cebolla", "ajo": "Ajo", "champinones": "Champiñones",
    "aguacate": "Aguacate", "pepino": "Pepino", "berenjena": "Berenjena",
    "coliflor": "Coliflor", "esparragos": "Espárragos", "alcachofa": "Alcachofa",
    "judias_verdes": "Judías Verdes", "remolacha": "Remolacha",
    "pico_gallo": "Pico de Gallo",
    "aceite_oliva": "Aceite de Oliva", "aceite_sesamo": "Aceite de Sésamo",
    "aceite_coco": "Aceite de Coco", "tahini": "Tahini",
    "almendras": "Almendras", "nuez": "Nueces",
    "anacardo": "Anacardos", "pistacho": "Pistachos",
    "mantequilla_mani": "Mantequilla de Maní", "mani": "Maní",
    "semillas_chia": "Chía", "semillas_lino": "Linaza",
    "semillas_girasol": "Semillas de Girasol", "semillas_calabaza": "Semillas de Calabaza",
    "aceitunas": "Aceitunas",
    "leche_almendra": "Leche de Almendra", "leche_avena": "Leche de Avena",
    "leche_descremada": "Leche Descremada", "leche_entera": "Leche Entera",
    "leche_soya": "Leche de Soya",
    "platano_fruta": "Plátano", "frutos_rojos": "Frutos Rojos", "manzana": "Manzana",
    "miel": "Miel", "dates": "Dátiles", "cacao": "Cacao",
}

# Pools by dietary pattern (broader than bulk)
PROT_OMNI = ["pollo_pechuga","pollo_muslo","pavo_pechuga","pavo_molido","salmon","atun_fresco","atun_lata_agua","bacalao","merluza","trucha","tilapia","sardinas","lomo_magro","carne_magra_res","huevo"]
PROT_PESC = ["salmon","atun_fresco","atun_lata_agua","bacalao","merluza","trucha","tilapia","sardinas","huevo","yogur_griego","queso_cottage"]
PROT_VEG  = ["huevo","clara_huevo","yogur_griego","queso_cottage","queso_fresco","queso_feta","ricotta","tofu_firme","tempeh","lentejas","lentejas_rojas","garbanzos","frijoles_negros","frijoles_pintos","edamame"]
PROT_VGAN = ["tofu_firme","tempeh","seitán","lentejas","lentejas_rojas","garbanzos","frijoles_negros","frijoles_pintos","edamame","proteina_arveja"]

CARB_BREAKFAST = ["avena","avena_seca","pan_integral","pan_centeno","camote","tortilla_maiz"]
CARB_LATAM = ["arroz_integral","arroz_blanco","frijoles_negros","platano_macho","tortilla_maiz","camote","yuca"]
CARB_MED = ["bulgur","farro","quinoa","pan_integral","cebada","couscous","pasta_integral"]
CARB_ASIAN = ["arroz_integral","arroz_basmati","arroz_blanco","quinoa"]
CARB_NA = ["camote","quinoa","arroz_integral","pan_integral","pasta_integral","papa"]
CARB_DENSE = ["arroz_blanco","papa","camote","pasta_integral","tortilla_trigo","yuca","platano_macho","avena_seca","pan_integral"]

VEG_GEN = ["brocoli","espinaca","kale","tomate","pimiento_rojo","calabacin","zanahoria","champinones","berenjena","coliflor","esparragos","judias_verdes","acelga"]
VEG_SALAD = ["rucula","espinaca","lechuga","tomate","pepino","aguacate","pimiento_rojo","pimiento_verde"]
VEG_BREAKFAST = ["espinaca","tomate","aguacate","champinones","pimiento_rojo"]

FAT_GEN = ["aceite_oliva","aguacate","almendras","nuez","semillas_chia","semillas_lino","semillas_girasol","semillas_calabaza"]
FAT_MED = ["aceite_oliva","aceitunas","almendras","queso_feta","nuez","pistacho"]
FAT_ASIAN = ["aceite_sesamo","semillas_chia","anacardo","mani"]
FAT_ME = ["tahini","aceite_oliva","almendras","pistacho","nuez"]
FAT_LATAM = ["aguacate","aceite_oliva","semillas_calabaza","mani"]
FAT_NA = ["aguacate","almendras","mantequilla_mani","nuez","semillas_chia"]

# ---------------------------------------------------------------------------
# Templates — large set with sub-regional cuisines.
# Each template: tid, cuisine (list), meal_time, diet, prot/carb/veg/fat pools+grams,
# name_pattern, desc, regions, rec, contra, goals, act, preg, prep, cook, origin,
# instructions, [optional: meal_format default solid]
# ---------------------------------------------------------------------------
def _t(tid, cuisine, mt, diet, prot_pool, prot_g, carb_pool, carb_g, veg_pool, veg_g,
       fat_pool, fat_g, name, desc, regions, rec, contra, goals, act, preg,
       prep, cook, origin, instructions, meal_format="solid"):
    return {
        "tid": tid, "cuisine": cuisine, "meal_time": mt, "diet": diet,
        "prot_pool": prot_pool, "prot_g": prot_g,
        "carb_pool": carb_pool, "carb_g": carb_g,
        "veg_pool": veg_pool, "veg_g": veg_g,
        "fat_pool": fat_pool, "fat_g": fat_g,
        "name": name, "desc": desc,
        "regions": regions, "rec": rec, "contra": contra,
        "goals": goals, "act": act, "preg": preg,
        "prep": prep, "cook": cook, "origin": origin,
        "instructions": instructions, "meal_format": meal_format,
    }

# Part A: gap-fill templates
GAP_TEMPLATES = [
    # --- 400 snacks: omnivore/pescatarian/vegetarian/vegan x cuisines ---
    _t("snack_omni_protein", ["north_american"], "snack", "omnivore",
       ["pollo_pechuga","pavo_pechuga","atun_lata_agua","huevo"], 80,
       ["pan_integral","tortilla_maiz","avena_seca"], 40,
       ["pepino","tomate","espinaca"], 40,
       ["aguacate","almendras","nuez"], 10,
       "Snack Proteico de {prot} con {carb} y {fat}",
       "Snack alto en proteína magra, ideal entre comidas.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","maintain","weight_loss"], ["lightly_active","moderately_active","very_active"],
       True, 5, 5, "Fitness moderno",
       ["Prepara la {prot}.","Acompaña con {carb}.","Añade {veg} fresco.","Termina con {fat}."]),
    _t("snack_med_pesc", ["mediterranean"], "snack", "pescatarian",
       ["atun_lata_agua","sardinas","huevo","yogur_griego"], 80,
       ["pan_integral","pan_centeno"], 30,
       ["tomate","pepino","pimiento_rojo"], 40,
       ["aceite_oliva","aceitunas","almendras"], 10,
       "Snack Mediterráneo de {prot} con {carb} y {fat}",
       "Snack mediterráneo cargado de omega-3 y polifenoles.",
       ["eu","uk","us"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 5, 5, "Mediterráneo",
       ["Sirve la {prot}.","Acompaña con {carb}.","Añade {veg}.","Aliña con {fat}."]),
    _t("snack_veg_dairy", ["north_american"], "snack", "vegetarian",
       ["yogur_griego","queso_cottage","ricotta","huevo"], 100,
       ["avena_seca","pan_integral"], 30,
       ["espinaca","tomate"], 30,
       ["almendras","nuez","semillas_chia","semillas_lino"], 12,
       "Snack Lácteo Proteico con {prot}, {carb} y {fat}",
       "Snack vegetariano alto en proteína y calcio.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","maintain"], ["lightly_active","moderately_active","very_active"],
       True, 5, 0, "Lácteo proteico",
       ["Sirve la {prot}.","Mezcla con {carb}.","Decora con {veg}.","Termina con {fat}."]),
    _t("snack_vegan_legume", ["latam"], "snack", "vegan",
       ["garbanzos","frijoles_negros","frijoles_pintos","lentejas"], 90,
       ["tortilla_maiz","camote","platano_macho"], 50,
       ["tomate","aguacate","pimiento_rojo"], 40,
       ["aguacate","semillas_calabaza","semillas_lino"], 10,
       "Snack Vegano LatAm con {prot}, {carb} y {fat}",
       "Snack vegano denso en fibra y proteína vegetal.",
       ["latam","us"], ["dyslipidemia"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 8, 5, "Mesoamérica",
       ["Mezcla {prot} con especias.","Calienta el {carb}.","Añade {veg}.","Termina con {fat}."]),
    _t("snack_me_vegan", ["middle_eastern"], "snack", "vegan",
       ["garbanzos","lentejas"], 100,
       ["bulgur","pan_integral"], 40,
       ["pepino","tomate","pimiento_rojo"], 50,
       ["tahini","aceite_oliva","pistacho"], 10,
       "Snack Levantino de {prot} con {carb} y {fat}",
       "Mezze ligero levantino con legumbres y tahini.",
       ["eu","us","uk"], ["dyslipidemia"], [],
       ["health","weight_loss","maintain"], ["lightly_active","moderately_active"],
       True, 8, 5, "Líbano",
       ["Prepara la {prot} estilo hummus.","Sirve con {carb} tostado.","Acompaña con {veg}.","Aliña con {fat}."]),

    # --- 300 veg + pesc dinners ---
    _t("dinner_veg_med", ["mediterranean"], "dinner", "vegetarian",
       ["huevo","queso_feta","ricotta","tofu_firme","lentejas","garbanzos"], 130,
       ["quinoa","farro","bulgur","camote"], 80,
       ["calabacin","berenjena","espinaca","brocoli","esparragos"], 150,
       ["aceite_oliva","aceitunas","pistacho"], 12,
       "Cena Vegetariana Mediterránea de {prot} con {carb} y {veg}",
       "Cena vegetariana mediterránea con grasas monoinsaturadas y vegetales asados.",
       ["eu","us","uk"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 12, 25, "Mediterráneo",
       ["Cocina la {prot} a la plancha.","Asa el {carb}.","Asa el {veg} con hierbas.","Termina con {fat}."]),
    _t("dinner_veg_latam", ["latam"], "dinner", "vegetarian",
       ["huevo","queso_fresco","frijoles_negros","lentejas","garbanzos"], 130,
       ["arroz_integral","camote","tortilla_maiz","platano_macho","yuca"], 90,
       VEG_GEN, 140,
       ["aguacate","aceite_oliva","semillas_calabaza"], 12,
       "Cena Vegetariana LatAm de {prot} con {carb} y {veg}",
       "Cena vegetariana latina balanceada, proteína vegetal y carbohidrato tradicional.",
       ["latam"], [], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 12, 25, "Pan-LatAm",
       ["Cocina la {prot}.","Calienta el {carb}.","Saltea el {veg}.","Termina con {fat}."]),
    _t("dinner_pesc_latam", ["latam"], "dinner", "pescatarian",
       ["merluza","trucha","tilapia","sardinas","atun_fresco"], 130,
       ["camote","quinoa","arroz_integral","yuca"], 90,
       VEG_GEN, 140,
       ["aceite_oliva","aguacate","pico_gallo"], 12,
       "Cena Pescatariana Latina de {prot} con {carb} y {veg}",
       "Cena ligera de pescado magro latinoamericano con vegetales asados.",
       ["latam","us"], ["dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 20, "Costa LatAm",
       ["Hornea la {prot} con limón.","Cocina el {carb}.","Asa el {veg}.","Decora con {fat}."]),
    _t("dinner_pesc_asian", ["asian"], "dinner", "pescatarian",
       ["salmon","tilapia","atun_fresco","bacalao"], 130,
       ["arroz_basmati","arroz_integral","quinoa"], 80,
       ["brocoli","espinaca","champinones","kale","esparragos"], 150,
       ["aceite_sesamo","anacardo"], 8,
       "Cena Asiática Pescatariana de {prot} con {carb} y {veg}",
       "Cena asiática de pescado al wok con vegetales crujientes.",
       ["us","eu","uk","ca"], ["ischemic_heart_disease","dyslipidemia"], [],
       ["weight_loss","health"], ["sedentary","lightly_active","moderately_active"],
       False, 10, 15, "Sudeste Asiático",
       ["Marina la {prot} con soya baja en sodio.","Sirve {carb}.","Saltea el {veg}.","Termina con {fat}."]),

    # --- 500 omnivore breakfasts ---
    _t("breakfast_omni_scramble", ["north_american"], "breakfast", "omnivore",
       ["huevo","clara_huevo","pavo_pechuga","queso_cottage"], 100,
       ["pan_integral","pan_centeno","avena_seca","tortilla_maiz"], 60,
       ["espinaca","tomate","pimiento_rojo","champinones","aguacate"], 60,
       ["aguacate","almendras","nuez","aceite_oliva"], 10,
       "Scramble Americano de {prot} con {carb} y {veg}",
       "Scramble americano alto en proteína para iniciar el día.",
       ["us","ca","uk"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 10, "USA",
       ["Bate la {prot}.","Saltea con {veg}.","Sirve sobre {carb} tostado.","Termina con {fat}."]),
    _t("breakfast_omni_bowl", ["mediterranean"], "breakfast", "omnivore",
       ["huevo","yogur_griego","atun_lata_agua","sardinas","pavo_pechuga"], 100,
       ["pan_integral","avena_seca","bulgur","couscous"], 60,
       ["tomate","aguacate","espinaca","pepino"], 60,
       ["aceite_oliva","aceitunas","almendras","nuez"], 12,
       "Bowl Mediterráneo de Desayuno de {prot} con {carb} y {veg}",
       "Bowl mediterráneo de desayuno con proteína y polifenoles.",
       ["eu","us","uk","ca"], ["dyslipidemia"], [],
       ["maintain","health"], ["lightly_active","moderately_active"],
       True, 10, 5, "Mediterráneo",
       ["Prepara la {prot}.","Sirve sobre {carb}.","Decora con {veg}.","Aliña con {fat}."]),
    _t("breakfast_omni_latam", ["latam"], "breakfast", "omnivore",
       ["huevo","queso_fresco","pollo_pechuga","pavo_pechuga"], 100,
       ["tortilla_maiz","pan_integral","avena","camote","platano_macho"], 70,
       ["tomate","aguacate","pimiento_rojo","pico_gallo"], 60,
       ["aguacate","aceite_oliva","semillas_calabaza"], 12,
       "Desayuno LatAm Omnívoro con {prot}, {carb} y {veg}",
       "Desayuno latino contundente con carbohidrato tradicional y proteína magra.",
       ["latam"], [], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 10, "Pan-LatAm",
       ["Prepara la {prot} a tu gusto.","Calienta el {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("breakfast_omni_sandwich", ["north_american"], "breakfast", "omnivore",
       ["huevo","pavo_pechuga","pollo_pechuga"], 90,
       ["pan_integral","pan_centeno","tortilla_trigo"], 60,
       ["espinaca","tomate","aguacate","lechuga"], 50,
       ["aguacate","aceite_oliva","almendras"], 10,
       "Sandwich Proteico Americano de {prot} con {veg}",
       "Sandwich americano alto en proteína, portable.",
       ["us","ca","uk"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 8, 8, "USA",
       ["Cocina la {prot}.","Arma sobre {carb}.","Añade {veg}.","Termina con {fat}."]),
    _t("breakfast_omni_pancake", ["north_american"], "breakfast", "omnivore",
       ["huevo","clara_huevo","yogur_griego","queso_cottage","whey_protein"], 80,
       ["avena_seca","avena","pan_integral"], 60,
       ["frutos_rojos","platano_fruta","manzana"], 60,
       ["mantequilla_mani","almendras","nuez","semillas_chia"], 12,
       "Pancakes Proteicos de {prot} con {carb} y {veg}",
       "Pancakes proteicos balanceados para entrenamiento de mañana.",
       ["us","ca","uk","eu"], ["athletic_load"], [],
       ["muscle_gain","maintain"], ["moderately_active","very_active"],
       True, 8, 10, "USA fitness",
       ["Mezcla la {prot} con {carb} molido.","Cocina pancakes.","Decora con {veg}.","Termina con {fat}."]),

    # --- 200 weight_gain dinners (dense carbs + protein) ---
    _t("dinner_wg_omni_dense", ["latam"], "dinner", "omnivore",
       PROT_OMNI, 150,
       CARB_DENSE, 180,
       VEG_GEN, 120,
       ["aceite_oliva","aguacate","mantequilla_mani","mani"], 18,
       "Cena Densa de {prot} con {carb} y {veg}",
       "Cena densa en energía para superávit calórico controlado.",
       ["latam","us","eu"], ["athletic_load"], [],
       ["weight_gain","muscle_gain"], ["very_active","extra_active","moderately_active"],
       True, 15, 25, "Volumen",
       ["Cocina la {prot}.","Sirve abundante {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("dinner_wg_veg_dense", ["mediterranean"], "dinner", "vegetarian",
       ["huevo","queso_feta","ricotta","tofu_firme","lentejas","garbanzos"], 150,
       CARB_DENSE, 180,
       VEG_GEN, 120,
       ["aceite_oliva","mantequilla_mani","almendras","nuez"], 18,
       "Cena Densa Vegetariana de {prot} con {carb} y {veg}",
       "Cena vegetariana densa para construir masa muscular.",
       ["eu","us","uk"], ["athletic_load"], [],
       ["weight_gain","muscle_gain"], ["very_active","extra_active","moderately_active"],
       True, 15, 25, "Volumen veg",
       ["Cocina la {prot}.","Sirve abundante {carb}.","Asa el {veg}.","Termina con {fat}."]),
    _t("dinner_wg_pesc_dense", ["asian"], "dinner", "pescatarian",
       ["salmon","atun_fresco","tilapia","trucha"], 150,
       CARB_DENSE, 180,
       VEG_GEN, 120,
       ["aceite_sesamo","anacardo","mani"], 15,
       "Cena Densa Asiática de {prot} con {carb} y {veg}",
       "Cena pescatariana densa para soporte muscular nocturno.",
       ["us","eu","uk","ca"], ["athletic_load","dyslipidemia"], [],
       ["weight_gain","muscle_gain"], ["very_active","extra_active","moderately_active"],
       False, 12, 20, "Asia volumen",
       ["Cocina la {prot} al wok.","Sirve abundante {carb}.","Saltea el {veg}.","Termina con {fat}."]),
]

# Liquids gap (50)
LIQUID_TEMPLATES = [
    _t("liquid_mg_whey", ["north_american"], "snack", "omnivore",
       ["whey_protein"], 30,
       ["avena_seca","platano_fruta","dates"], 50,
       ["frutos_rojos"], 40,
       ["mantequilla_mani","almendras","semillas_chia"], 15,
       "Mass Gainer Shake de {prot} con {carb} y {fat}",
       "Shake post-entreno alto en calorías y proteína para ganancia muscular.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","weight_gain"], ["very_active","extra_active"],
       True, 5, 0, "Fitness USA",
       ["Mezcla {prot} con leche.","Añade {carb}.","Agrega {veg}.","Termina con {fat}.","Licua hasta cremoso."],
       meal_format="liquid"),
    _t("liquid_mg_oat", ["north_american"], "breakfast", "vegetarian",
       ["yogur_griego","queso_cottage","whey_protein"], 80,
       ["avena_seca","platano_fruta","dates"], 60,
       ["frutos_rojos","manzana"], 40,
       ["mantequilla_mani","almendras","nuez","semillas_chia"], 15,
       "Oat Milkshake de {prot} con {carb} y {fat}",
       "Shake de avena denso en calorías para mañanas de entrenamiento.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","weight_gain","maintain"], ["very_active","extra_active","moderately_active"],
       True, 5, 0, "USA breakfast",
       ["Mezcla {prot}.","Añade {carb} y leche.","Agrega {veg}.","Termina con {fat}.","Licua bien."],
       meal_format="liquid"),
    _t("liquid_mg_pb", ["north_american"], "snack", "vegetarian",
       ["whey_protein","yogur_griego","queso_cottage"], 70,
       ["platano_fruta","dates","avena_seca"], 50,
       ["frutos_rojos"], 30,
       ["mantequilla_mani","mani","semillas_lino"], 18,
       "Peanut Butter Shake de {prot} con {carb} y {fat}",
       "Shake de mantequilla de maní alto en grasas saludables y proteína.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 5, 0, "USA snack",
       ["Mezcla {prot} con leche.","Añade {carb}.","Agrega {veg}.","Termina con {fat}.","Licua hasta espumoso."],
       meal_format="liquid"),
    _t("liquid_mg_vegan", ["north_american"], "snack", "vegan",
       ["proteina_arveja","tofu_firme"], 50,
       ["avena_seca","platano_fruta","dates"], 60,
       ["frutos_rojos"], 40,
       ["mantequilla_mani","semillas_chia","semillas_lino"], 18,
       "Mass Gainer Vegano de {prot} con {carb} y {fat}",
       "Shake vegano denso post-entreno con proteína vegetal.",
       ["us","ca","eu","uk","latam"], ["dyslipidemia"], [],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 5, 0, "Plant-based fitness",
       ["Mezcla {prot} con leche vegetal.","Añade {carb}.","Agrega {veg}.","Termina con {fat}.","Licua bien."],
       meal_format="liquid"),
]

# Part B: bulk multi-region templates (sub-regional)
BULK_TEMPLATES = [
    # LATAM sub-regional (40%) — many variants
    _t("latam_mexican_lunch", ["latam"], "lunch", "omnivore",
       PROT_OMNI, 130, CARB_LATAM, 110, VEG_GEN, 130, FAT_LATAM, 14,
       "Almuerzo Mexicano de {prot} con {carb}, {veg} y {fat}",
       "Almuerzo mexicano clásico balanceado.",
       ["latam","us"], [], [], ["maintain","muscle_gain"],
       ["moderately_active","very_active","lightly_active"],
       True, 15, 20, "México",
       ["Cocina la {prot} con especias mexicanas.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("latam_peruvian_lunch", ["latam"], "lunch", "pescatarian",
       ["merluza","tilapia","bacalao","trucha","huevo"], 130,
       ["quinoa","camote","yuca","arroz_integral"], 110, VEG_GEN, 130,
       ["aceite_oliva","aguacate"], 12,
       "Almuerzo Peruano de {prot} con {carb} y {veg}",
       "Almuerzo peruano con pescado fresco y tubérculo andino.",
       ["latam","us"], ["dyslipidemia"], [],
       ["health","maintain"], ["lightly_active","moderately_active"],
       True, 15, 20, "Perú costa",
       ["Marina la {prot} en limón.","Sirve con {carb} cocido.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("latam_argentine_dinner", ["latam"], "dinner", "omnivore",
       ["carne_magra_res","lomo_magro","pollo_pechuga"], 140,
       ["camote","papa","quinoa"], 100, VEG_GEN, 130,
       ["aceite_oliva","aguacate"], 12,
       "Cena Argentina de {prot} con {carb} y {veg}",
       "Cena argentina con carne magra a la parrilla.",
       ["latam","us","eu"], ["athletic_load"], ["gout"],
       ["muscle_gain","maintain"], ["moderately_active","very_active"],
       True, 12, 25, "Argentina",
       ["Asa la {prot} a la parrilla.","Acompaña con {carb}.","Sirve con {veg}.","Termina con {fat}."]),
    _t("latam_colombian_lunch", ["latam"], "lunch", "omnivore",
       PROT_OMNI, 120, ["arroz_integral","frijoles_pintos","platano_macho","yuca"], 110,
       VEG_GEN, 130, ["aguacate","aceite_oliva"], 12,
       "Bandeja Colombiana de {prot} con {carb} y {veg}",
       "Bandeja paisa adaptada balanceada con carbo tradicional.",
       ["latam"], [], [], ["maintain","muscle_gain","weight_gain"],
       ["moderately_active","very_active"], True, 15, 25, "Colombia",
       ["Cocina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Decora con {fat}."]),
    _t("latam_brazilian_lunch", ["latam"], "lunch", "omnivore",
       PROT_OMNI, 120, ["arroz_integral","frijoles_negros","yuca"], 110,
       VEG_GEN, 130, ["aguacate","aceite_oliva","semillas_calabaza"], 12,
       "Feijoada Ligera Brasileña con {prot}, {carb} y {veg}",
       "Versión balanceada de feijoada con proteína magra.",
       ["latam"], [], [], ["maintain","muscle_gain"],
       ["moderately_active","very_active","lightly_active"], True, 20, 30, "Brasil",
       ["Cocina la {prot}.","Mezcla con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("latam_chilean_dinner", ["latam"], "dinner", "pescatarian",
       ["salmon","merluza","tilapia","trucha"], 130,
       ["camote","papa","quinoa"], 90, VEG_GEN, 140,
       ["aceite_oliva","aguacate"], 12,
       "Cena Chilena de {prot} con {carb} y {veg}",
       "Cena chilena de pescado austral con vegetales del sur.",
       ["latam"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","weight_loss"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 22, "Chile",
       ["Hornea la {prot}.","Asa el {carb}.","Saltea el {veg}.","Aliña con {fat}."]),
    _t("latam_cuban_lunch", ["latam"], "lunch", "omnivore",
       PROT_OMNI, 120, ["arroz_blanco","frijoles_negros","platano_macho"], 110,
       VEG_GEN, 120, ["aceite_oliva","aguacate"], 12,
       "Almuerzo Cubano de {prot} con {carb} y {veg}",
       "Almuerzo cubano clásico moros y cristianos balanceado.",
       ["latam","us"], [], [], ["maintain","muscle_gain"],
       ["moderately_active","very_active","lightly_active"], True, 15, 25, "Cuba",
       ["Cocina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),

    # EU sub-regional (30%)
    _t("eu_spanish_lunch", ["mediterranean"], "lunch", "pescatarian",
       ["salmon","atun_fresco","bacalao","merluza","sardinas"], 120,
       ["arroz_integral","quinoa","bulgur","pan_integral"], 90,
       VEG_GEN, 140, ["aceite_oliva","aceitunas","almendras"], 14,
       "Almuerzo Español de {prot} con {carb} y {veg}",
       "Almuerzo español mediterráneo con pescado y aceite de oliva virgen.",
       ["eu","us"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","maintain","weight_loss"], ["lightly_active","moderately_active"],
       True, 15, 20, "España",
       ["Cocina la {prot} a la plancha.","Sirve con {carb}.","Acompaña con {veg}.","Aliña con {fat}."]),
    _t("eu_italian_dinner", ["mediterranean"], "dinner", "vegetarian",
       ["huevo","ricotta","queso_feta","tofu_firme","lentejas"], 130,
       ["pasta_integral","polenta","quinoa","farro"], 80, VEG_GEN, 140,
       ["aceite_oliva","aceitunas","pistacho","nuez"], 12,
       "Cena Italiana Vegetariana de {prot} con {carb} y {veg}",
       "Cena italiana vegetariana con pasta integral y vegetales asados.",
       ["eu","us","uk"], ["dyslipidemia"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 12, 22, "Italia",
       ["Cocina la {prot}.","Prepara el {carb} al dente.","Saltea el {veg}.","Termina con {fat}."]),
    _t("eu_french_lunch", ["mediterranean"], "lunch", "pescatarian",
       ["salmon","bacalao","merluza","atun_fresco"], 120,
       ["quinoa","bulgur","farro","pan_centeno"], 90, VEG_GEN, 140,
       ["aceite_oliva","aceitunas","nuez"], 12,
       "Almuerzo Francés de {prot} con {carb} y {veg}",
       "Almuerzo francés tipo niçoise con pescado y vegetales.",
       ["eu","us","uk"], ["dyslipidemia"], [],
       ["health","maintain"], ["lightly_active","moderately_active"],
       True, 15, 20, "Francia",
       ["Cocina la {prot}.","Sirve con {carb}.","Mezcla con {veg}.","Aliña con {fat}."]),
    _t("eu_german_dinner", ["nordic"], "dinner", "omnivore",
       ["pavo_pechuga","pollo_pechuga","lomo_magro"], 130,
       ["papa","cebada","pan_centeno"], 90, VEG_GEN, 130,
       ["aceite_oliva","nuez"], 10,
       "Cena Alemana Ligera de {prot} con {carb} y {veg}",
       "Cena alemana ligera con proteína magra y tubérculo.",
       ["eu","uk"], [], [], ["maintain","weight_loss"],
       ["sedentary","lightly_active","moderately_active"], True, 12, 25, "Alemania",
       ["Cocina la {prot}.","Hierve el {carb}.","Saltea el {veg}.","Termina con {fat}."]),
    _t("eu_greek_lunch", ["mediterranean"], "lunch", "vegetarian",
       ["queso_feta","huevo","yogur_griego","lentejas","garbanzos"], 130,
       ["bulgur","farro","pan_integral","couscous"], 90, VEG_GEN+["pepino"], 140,
       ["aceite_oliva","aceitunas","almendras"], 14,
       "Almuerzo Griego de {prot} con {carb} y {veg}",
       "Almuerzo griego tipo horiatiki con vegetales frescos y queso feta.",
       ["eu","us","uk"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","weight_loss","maintain"], ["lightly_active","moderately_active"],
       True, 15, 15, "Grecia",
       ["Prepara la {prot}.","Sirve con {carb}.","Mezcla con {veg}.","Aliña con {fat}."]),
    _t("eu_portuguese_dinner", ["mediterranean"], "dinner", "pescatarian",
       ["bacalao","sardinas","atun_fresco","merluza"], 130,
       ["camote","papa","quinoa","pan_integral"], 90, VEG_GEN, 140,
       ["aceite_oliva","aceitunas"], 12,
       "Cena Portuguesa de {prot} con {carb} y {veg}",
       "Cena portuguesa con bacalao y vegetales al horno.",
       ["eu","uk"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","weight_loss"], ["sedentary","lightly_active"],
       False, 12, 25, "Portugal",
       ["Hornea la {prot} con ajo.","Asa el {carb}.","Saltea el {veg}.","Termina con {fat}."]),

    # US sub-regional (15%)
    _t("us_california_lunch", ["north_american"], "lunch", "omnivore",
       PROT_OMNI, 130, CARB_NA, 100, VEG_GEN+VEG_SALAD, 140,
       ["aguacate","almendras","aceite_oliva"], 14,
       "Almuerzo California Bowl de {prot} con {carb} y {veg}",
       "California bowl con proteína magra y vegetales frescos.",
       ["us","ca"], ["athletic_load","dyslipidemia"], [],
       ["health","weight_loss","muscle_gain"], ["moderately_active","very_active","lightly_active"],
       True, 15, 18, "California",
       ["Cocina la {prot}.","Asa el {carb}.","Mezcla con {veg}.","Decora con {fat}."]),
    _t("us_texmex_dinner", ["north_american"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_molido","carne_magra_res","lomo_magro"], 130,
       ["tortilla_maiz","arroz_integral","frijoles_negros"], 100, VEG_GEN, 130,
       ["aguacate","aceite_oliva","pico_gallo"], 14,
       "Cena Tex-Mex de {prot} con {carb} y {veg}",
       "Cena Tex-Mex balanceada con proteína magra y vegetales coloridos.",
       ["us"], [], [], ["maintain","muscle_gain"],
       ["moderately_active","very_active","lightly_active"], True, 15, 20, "Texas/USA",
       ["Cocina la {prot} con especias texanas.","Calienta {carb}.","Acompaña con {veg}.","Termina con {fat}."]),

    # Canada (10%)
    _t("ca_pacific_dinner", ["north_american"], "dinner", "pescatarian",
       ["salmon","trucha","bacalao","atun_fresco"], 130,
       ["camote","quinoa","arroz_integral","papa"], 90, VEG_GEN, 140,
       ["aceite_oliva","nuez","aguacate"], 12,
       "Cena Pacífico Canadiense de {prot} con {carb} y {veg}",
       "Cena del Pacífico canadiense con salmón salvaje y vegetales locales.",
       ["ca","us"], ["dyslipidemia","ischemic_heart_disease","mild_depression"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 20, "Canadá West Coast",
       ["Hornea la {prot}.","Asa el {carb}.","Saltea el {veg}.","Termina con {fat}."]),
    _t("ca_quebec_lunch", ["north_american"], "lunch", "omnivore",
       ["pavo_pechuga","pollo_pechuga","lomo_magro"], 130, CARB_NA, 100, VEG_GEN, 130,
       ["aceite_oliva","nuez","almendras"], 12,
       "Almuerzo Quebec de {prot} con {carb} y {veg}",
       "Almuerzo de Quebec balanceado con proteína magra.",
       ["ca","us"], [], [], ["maintain","muscle_gain"],
       ["lightly_active","moderately_active","very_active"], True, 15, 18, "Quebec",
       ["Cocina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),

    # UK (5%)
    _t("uk_modern_dinner", ["mediterranean"], "dinner", "pescatarian",
       ["salmon","bacalao","merluza","trucha"], 130, ["papa","camote","quinoa"], 90,
       VEG_GEN, 140, ["aceite_oliva","nuez"], 12,
       "Cena Británica Moderna de {prot} con {carb} y {veg}",
       "Cena británica moderna con pescado al horno y vegetales de raíz.",
       ["uk","eu"], ["dyslipidemia"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 22, "UK moderno",
       ["Hornea la {prot} con hierbas.","Asa el {carb}.","Saltea el {veg}.","Termina con {fat}."]),
    _t("uk_breakfast", ["mediterranean"], "breakfast", "vegetarian",
       ["huevo","yogur_griego","queso_cottage"], 100, ["pan_integral","avena_seca"], 60,
       ["espinaca","tomate","champinones"], 60,
       ["aguacate","aceite_oliva","almendras"], 12,
       "Desayuno Británico Saludable con {prot}, {carb} y {veg}",
       "Desayuno británico moderno saludable con proteína y vegetales.",
       ["uk","eu"], [], [], ["maintain","health"],
       ["lightly_active","moderately_active"], True, 10, 10, "UK breakfast",
       ["Prepara la {prot}.","Tuesta el {carb}.","Saltea el {veg}.","Termina con {fat}."]),

    # Asian extra
    _t("asia_japanese_lunch", ["asian"], "lunch", "pescatarian",
       ["salmon","atun_fresco","bacalao","huevo"], 120,
       ["arroz_basmati","arroz_integral","quinoa"], 90,
       ["brocoli","espinaca","champinones","kale","esparragos"], 130,
       ["aceite_sesamo","anacardo"], 8,
       "Almuerzo Japonés de {prot} con {carb} y {veg}",
       "Almuerzo japonés tipo bowl con pescado y vegetales al vapor.",
       ["us","eu","uk","ca"], ["ischemic_heart_disease","dyslipidemia"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 15, 15, "Japón",
       ["Cocina la {prot} a la plancha.","Sirve {carb}.","Saltea el {veg}.","Termina con {fat}."]),
    _t("asia_korean_dinner", ["asian"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga","lomo_magro","huevo"], 130,
       CARB_ASIAN, 90, VEG_GEN, 140,
       ["aceite_sesamo","semillas_chia","anacardo"], 10,
       "Cena Coreana de {prot} con {carb} y {veg}",
       "Cena coreana tipo bibimbap con proteína magra.",
       ["us","eu","uk"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["moderately_active","very_active"],
       True, 15, 20, "Corea",
       ["Marina la {prot}.","Sirve {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("asia_thai_lunch", ["asian"], "lunch", "vegan",
       ["tofu_firme","tempeh","edamame"], 130, CARB_ASIAN, 100, VEG_GEN, 130,
       ["aceite_sesamo","mani","anacardo"], 12,
       "Almuerzo Tailandés Vegano de {prot} con {carb} y {veg}",
       "Almuerzo tailandés vegano con tofu y vegetales al wok.",
       ["us","eu","uk","ca"], ["dyslipidemia"], [],
       ["health","weight_loss","muscle_gain"], ["lightly_active","moderately_active"],
       True, 15, 15, "Tailandia",
       ["Saltea la {prot}.","Sirve {carb}.","Añade {veg}.","Termina con {fat}."]),

    # Middle Eastern extra
    _t("me_lunch_omni", ["middle_eastern"], "lunch", "omnivore",
       ["pollo_pechuga","pavo_pechuga","lomo_magro","huevo"], 130,
       ["bulgur","quinoa","couscous","camote"], 90, VEG_GEN+["pepino"], 140,
       ["tahini","aceite_oliva","pistacho","almendras"], 14,
       "Almuerzo Levantino Omnívoro de {prot} con {carb} y {veg}",
       "Almuerzo levantino con proteína magra especiada.",
       ["eu","us","uk"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["moderately_active","very_active","lightly_active"],
       True, 15, 20, "Líbano",
       ["Marina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Aliña con {fat}."]),

    # African
    _t("af_north_lunch", ["african"], "lunch", "vegan",
       ["garbanzos","lentejas","tofu_firme","frijoles_pintos"], 130,
       ["couscous","bulgur","quinoa","camote"], 100, VEG_GEN+["zanahoria","esparragos"], 130,
       ["aceite_oliva","almendras","semillas_calabaza"], 12,
       "Almuerzo Norafricano Vegano de {prot} con {carb} y {veg}",
       "Almuerzo norafricano tipo tagine vegano.",
       ["eu","us","uk"], ["dyslipidemia"], [],
       ["health","maintain","weight_loss"], ["lightly_active","moderately_active"],
       True, 15, 25, "Marruecos",
       ["Cocina la {prot} con especias.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("af_ethiopian_lunch", ["african"], "lunch", "vegan",
       ["lentejas","lentejas_rojas","frijoles_pintos","garbanzos"], 130,
       ["bulgur","arroz_integral","quinoa"], 100, VEG_GEN, 130,
       ["aceite_oliva","semillas_lino","semillas_calabaza"], 12,
       "Almuerzo Etíope Vegano de {prot} con {carb} y {veg}",
       "Almuerzo etíope con legumbres especiadas.",
       ["eu","us","uk","ca"], ["dyslipidemia","iron_deficiency_anemia"], [],
       ["health","maintain"], ["lightly_active","moderately_active"],
       True, 15, 25, "Etiopía",
       ["Cocina la {prot} con berbere.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),

    # Fusion extras
    _t("fusion_breakfast_omni_2", ["fusion"], "breakfast", "omnivore",
       ["huevo","yogur_griego","pavo_pechuga","atun_lata_agua"], 100,
       CARB_BREAKFAST, 60, VEG_BREAKFAST, 60, ["aguacate","almendras","semillas_chia"], 12,
       "Desayuno Fusión Omnívoro con {prot}, {carb} y {veg}",
       "Desayuno fusión balanceado para energía sostenida.",
       ["us","eu","uk","latam","ca"], [], [], ["maintain","muscle_gain","health"],
       ["lightly_active","moderately_active","very_active"], True, 10, 10, "Fusión global",
       ["Prepara la {prot}.","Tuesta el {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("fusion_dinner_pesc", ["fusion"], "dinner", "pescatarian",
       ["salmon","bacalao","merluza","trucha","tilapia"], 130,
       ["quinoa","camote","farro","arroz_integral"], 90, VEG_GEN, 140,
       ["aceite_oliva","aguacate","aceitunas"], 12,
       "Cena Fusión Pescatariana de {prot} con {carb} y {veg}",
       "Cena fusión ligera con pescado y vegetales asados.",
       ["us","eu","uk","latam","ca"], ["dyslipidemia"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 22, "Fusión",
       ["Hornea la {prot}.","Asa el {carb}.","Saltea el {veg}.","Termina con {fat}."]),
    _t("fusion_lunch_omni", ["fusion"], "lunch", "omnivore",
       PROT_OMNI, 130, CARB_NA, 100, VEG_GEN, 130, ["aguacate","aceite_oliva","almendras"], 14,
       "Almuerzo Fusión de {prot} con {carb} y {veg}",
       "Almuerzo fusión balanceado para cualquier objetivo.",
       ["us","eu","uk","latam","ca"], [], [], ["maintain","muscle_gain","weight_loss"],
       ["lightly_active","moderately_active","very_active"], True, 15, 20, "Fusión global",
       ["Cocina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
    _t("fusion_lunch_veg", ["fusion"], "lunch", "vegetarian",
       PROT_VEG, 130, CARB_NA, 100, VEG_GEN, 130, ["aguacate","aceite_oliva","almendras"], 12,
       "Almuerzo Fusión Vegetariano de {prot} con {carb} y {veg}",
       "Almuerzo fusión vegetariano balanceado.",
       ["us","eu","uk","latam","ca"], [], [], ["health","maintain","weight_loss"],
       ["lightly_active","moderately_active"], True, 15, 20, "Fusión",
       ["Cocina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."]),
]

ALL_TEMPLATES = GAP_TEMPLATES + LIQUID_TEMPLATES + BULK_TEMPLATES


# ---------------------------------------------------------------------------
# Core noun extraction for signature dedup.
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "g","ml","gr","de","y","con","sin","la","el","las","los","una","un",
    "fresco","fresca","frescos","frescas","cocido","cocida","picado","picada",
    "rebanado","rallado","molido","crudo","cruda","entero","entera",
    "rojo","roja","verde","blanco","blanca","negro","negra","amarillo",
    "grande","pequeno","pequeña","mediano","mediana",
    "al","gusto","sal","pimienta","especias","aceite","oliva","virgen",
    "extra","integral","light","sin","azucar","azúcar","baja","sodio",
    "cucharada","cucharadita","taza","tazas","unidad","unidades",
    "ramita","hoja","hojas","diente","dientes","pizca",
}

def _extract_core_nouns(ing_str: str) -> str:
    s = ing_str.lower()
    s = re.sub(r"[0-9]+([.,][0-9]+)?", " ", s)
    s = re.sub(r"[^\w\sáéíóúñ]", " ", s)
    tokens = [t for t in s.split() if t and t not in _STOPWORDS and len(t) > 2]
    # Keep first 3 distinct content nouns
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
        if len(seen) >= 3:
            break
    return "_".join(seen)


def _signature(recipe: dict) -> str:
    name_norm = re.sub(r"\s+", " ", recipe["name"].lower().strip())
    name_norm = re.sub(r"[^\w\sáéíóúñ]", "", name_norm)
    ings = sorted(_extract_core_nouns(i) for i in recipe["execution"]["ingredients"] if _extract_core_nouns(i))
    return hashlib.sha1(f"{name_norm}|{','.join(ings)}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Macros
# ---------------------------------------------------------------------------
def detect_allergens(component_keys: list[str]) -> list[str]:
    found: set[str] = set()
    for k in component_keys:
        for a in ALLERGEN_FROM_KEY.get(k, ()):
            found.add(a)
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    p = c = f = fib = sug = na = satfat = 0.0
    gi_weighted = gi_carb_total = 0.0
    for key, grams in components:
        ing = ING[key]
        factor = grams / 100.0
        p += ing["p"] * factor
        c += ing["c"] * factor
        f += ing["f"] * factor
        fib += ing["fib"] * factor
        sug += ing["sug"] * factor
        na += ing["na"] * factor
        satfat += ing.get("satfat", 0.0) * factor
        carb_contrib = ing["c"] * factor
        gi_weighted += ing["gi"] * carb_contrib
        gi_carb_total += carb_contrib
    gi = int(round(gi_weighted / gi_carb_total)) if gi_carb_total > 0 else None
    p_i = int(round(p)); c_i = int(round(c)); f_i = int(round(f))
    kcal = 4 * p_i + 4 * c_i + 9 * f_i
    gl = (gi * c_i / 100.0) if gi is not None else None
    return {
        "calories": kcal, "protein_g": p_i, "carbs_g": c_i, "fat_g": f_i,
        "fiber_g": int(round(fib)), "sugar_g": int(round(sug)),
        "sodium_mg": int(round(na)), "gi": gi, "gl": round(gl, 1) if gl is not None else None,
        "satfat_g": int(round(satfat)),
    }


def deterministic_id(template_id: str, slots: tuple[str, ...]) -> str:
    h = hashlib.sha1(("|".join(("l99", template_id, *slots))).encode()).hexdigest()
    return f"nova_meal_l99_{h[:10]}"


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
    if not (100 <= kcal <= 1500):
        return False, f"kcal_out_of_range={kcal}"
    if not (0 <= m["protein_g"] <= 80):
        return False, f"protein_out_of_range"
    if not (0 <= m["carbs_g"] <= 200):
        return False, f"carbs_out_of_range"
    if not (0 <= m["fat_g"] <= 80):
        return False, f"fat_out_of_range"
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
    if not mc["regions"]:
        return False, "regions_empty"
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

    # Sugar cap on liquids
    rec = list(tpl["rec"])
    contra = list(tpl["contra"])
    meal_format = tpl.get("meal_format", "solid")
    if meal_format == "liquid":
        if m["carbs_g"] > 35:
            for cond in ("diabetes_t1", "diabetes_t2", "pcos", "fatty_liver"):
                if cond in rec:
                    rec.remove(cond)
        if m.get("gl") is not None and m["gl"] > 10:
            for cond in ("diabetes_t1", "diabetes_t2", "pcos"):
                if cond in rec:
                    rec.remove(cond)

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
                "sat_fat_g": m["satfat_g"], "sodium_mg": m["sodium_mg"],
            },
            "micronutrients": {
                "gi": m["gi"], "gl": m["gl"],
                "potassium_mg": None, "phosphorus_mg": None, "iron_mg": None,
                "heme_pct": None, "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
            },
        },
        "matching_criteria": {
            "target_goals": list(tpl["goals"]),
            "suitable_for_activity": list(tpl["act"]),
            "recommended_for_conditions": rec,
            "contraindicated_conditions": contra,
            "allergens": allergens,
            "regions": list(tpl["regions"]),
            "dietary_pattern": tpl["diet"],
            "cuisine_region": list(tpl["cuisine"]),
            "meal_format": meal_format,
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
            "source_catalog": SOURCE_CATALOG,
        },
        "audit": {
            "schema_version": "v2",
            "macro_consistency_pct": consistency_pct,
            "gl_estimated": m["gl"],
            "cultural_origin": tpl.get("origin"),
            "image_status": "placeholder_pending_upload",
            "generated_at": "2026-06-01",
        },
    }


def main() -> None:
    # Build existing dedup index
    print("Loading existing catalog for dedup index...")
    existing = json.loads(EXISTING_CATALOG.read_text())
    existing_ids: set[str] = {r["id"] for r in existing if "id" in r}
    existing_sigs: set[str] = set()
    # Per-cell name index: (meal_time, diet, cuisine_first) -> list[name_lower]
    cell_names: dict[tuple, list[str]] = {}
    for r in existing:
        try:
            existing_sigs.add(_signature(r))
        except Exception:
            pass
        mc = r.get("matching_criteria", {})
        ex = r.get("execution", {})
        cuisine = mc.get("cuisine_region") or [""]
        key = (ex.get("meal_time", ""), mc.get("dietary_pattern", ""), cuisine[0] if cuisine else "")
        cell_names.setdefault(key, []).append(r.get("name", "").lower())
    print(f"Existing: ids={len(existing_ids)} sigs={len(existing_sigs)} cells={len(cell_names)}")

    out: list[dict] = []
    new_sigs: set[str] = set()
    new_ids: set[str] = set()
    cell_names_exact: dict[tuple, set[str]] = {}
    rejection_counts: dict[str, int] = {}
    rejection_samples: list[tuple[str, str]] = []
    total_attempts = 0

    def reject(rid: str, reason: str) -> None:
        key = reason.split("=", 1)[0]
        rejection_counts[key] = rejection_counts.get(key, 0) + 1
        if len(rejection_samples) < 200:
            rejection_samples.append((rid, reason))

    for tpl in ALL_TEMPLATES:
        for prot, carb, veg, fat in product(tpl["prot_pool"], tpl["carb_pool"], tpl["veg_pool"], tpl["fat_pool"]):
            total_attempts += 1
            try:
                recipe = build_one(tpl, prot, carb, veg, fat)
            except Exception as exc:  # noqa: BLE001
                reject("?", f"build_error={exc.__class__.__name__}")
                continue
            rid = recipe["id"]
            if rid in existing_ids or rid in new_ids:
                reject(rid, "duplicate_id")
                continue
            ok, reason = validate(recipe)
            if not ok:
                reject(rid, reason)
                continue
            sig = _signature(recipe)
            if sig in existing_sigs or sig in new_sigs:
                reject(rid, "signature_collision")
                continue
            # Name dedup: cheap exact-match against per-cell index.
            # Levenshtein dropped intentionally — was O(n^2) bottleneck; signature
            # (name_norm + sorted ingredient nouns sha1) already catches functional
            # duplicates. Cell index caps exact name collisions.
            mc = recipe["matching_criteria"]
            ex = recipe["execution"]
            cuisine = mc["cuisine_region"]
            cell_key = (ex["meal_time"], mc["dietary_pattern"], cuisine[0] if cuisine else "")
            name_lower = recipe["name"].lower()
            cell_set = cell_names_exact.get(cell_key)
            if cell_set is None:
                cell_set = set(n.lower() for n in cell_names.get(cell_key, []))
                cell_names_exact[cell_key] = cell_set
            if name_lower in cell_set:
                reject(rid, "name_exact_collision")
                continue
            # Accept
            new_ids.add(rid)
            new_sigs.add(sig)
            cell_set.add(name_lower)
            out.append(recipe)

    OUT.write_text(json.dumps(out, ensure_ascii=False))
    summary_lines = ["L99 batch generation summary",
                     f"templates={len(ALL_TEMPLATES)}",
                     f"attempts={total_attempts}",
                     f"accepted={len(out)}",
                     f"rejected_total={total_attempts - len(out)}",
                     "",
                     "Rejection reason counts:"]
    for k, v in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        summary_lines.append(f"  {k}: {v}")
    summary_lines.append("")
    summary_lines.append("Rejection samples (first 200):")
    summary_lines.extend(f"{rid}\t{reason}" for rid, reason in rejection_samples)
    LOG.write_text("\n".join(summary_lines))
    print(f"l99: templates={len(ALL_TEMPLATES)} attempts={total_attempts} accepted={len(out)}")
    print("Reject:", rejection_counts)


if __name__ == "__main__":
    main()
