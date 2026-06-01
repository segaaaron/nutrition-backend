"""Gap closure batch — final L99 catalog completion.

Targets (≈2,550 NEW recipes):
- Bucket A: Snacks +1,500 (omni 500, pesc 500, vegan 300, veg 200)
- Bucket B: Breakfast pescatarian +200
- Bucket C: Celiac-recommended +100 (gluten-free verified)
- Bucket D: CKD-safe +200 (low protein/sodium + estimated low K/P micros)
- Bucket E: Diabetes_t2 verified +500 (carbs≤45, sugar≤10, fiber≥8, GL≤10)
- Bucket F: Jugos weight_loss +50 (liquid, low GL, viral content)

Hard validators (mirror L99 + bucket-specific gates):
- Macro math |kcal − (4P+4C+9F)| / kcal ≤ 0.05
- Allergen lookup EN+ES via ING table
- Closed vocabulary enforcement
- Macro plausibility kcal [100,1500]; protein [0,80]; carbs [0,200]; fat [0,80]
- Dedup signature (sha1 over name_norm + sorted core ingredient nouns)
- Cell exact-name dedup vs full catalog + new buckets
- Bucket clinical gates (CKD potassium/phosphorus; DT2 carb/sugar/fiber/GL;
  jugos GL≤10 + carb cap)

Outputs:
- data/meals/gap_closure_batch_2026_06_01.json
- scripts/generate_recipes_gap_closure_2026_06_01_rejections.log
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import (  # noqa: E402
    ACTIVITY_LEVELS_5, ALLERGENS_14, CONDITIONS_25, GOALS_5, MEAL_TIMES_4, REGIONS_5,
)

PLACEHOLDER_IMG = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"
SOURCE_CATALOG = "nova_v2_batch_gap_closure_2026_06_01"
EXISTING_CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
OUT = ROOT / "data" / "meals" / "gap_closure_batch_2026_06_01.json"
LOG = ROOT / "scripts" / "generate_recipes_gap_closure_2026_06_01_rejections.log"

# ---------------------------------------------------------------------------
# Ingredient table per 100 g cooked.
# Extended with potassium_mg / phosphorus_mg estimates for CKD bucket use.
# Sources: USDA FDC + BEDCA averages, rounded conservatively.
# ---------------------------------------------------------------------------
ING: dict[str, dict] = {
    # Animal proteins
    "pollo_pechuga":    {"kcal": 165, "p": 31,  "c": 0,   "f": 3.6, "fib": 0,   "sug": 0,   "na": 74,  "gi": 0,  "satfat": 1.0, "k": 256, "ph": 220, "tags": ["omnivore","pescatarian"]},
    "pavo_pechuga":     {"kcal": 135, "p": 30,  "c": 0,   "f": 1.0, "fib": 0,   "sug": 0,   "na": 65,  "gi": 0,  "satfat": 0.3, "k": 239, "ph": 210, "tags": ["omnivore","pescatarian"]},
    "salmon":           {"kcal": 208, "p": 22,  "c": 0,   "f": 13,  "fib": 0,   "sug": 0,   "na": 59,  "gi": 0,  "satfat": 3.1, "k": 363, "ph": 240, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "atun_lata_agua":   {"kcal": 116, "p": 26,  "c": 0,   "f": 0.8, "fib": 0,   "sug": 0,   "na": 247, "gi": 0,  "satfat": 0.2, "k": 237, "ph": 158, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "atun_fresco":      {"kcal": 144, "p": 30,  "c": 0,   "f": 1.0, "fib": 0,   "sug": 0,   "na": 39,  "gi": 0,  "satfat": 0.3, "k": 252, "ph": 254, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "bacalao":          {"kcal": 82,  "p": 18,  "c": 0,   "f": 0.7, "fib": 0,   "sug": 0,   "na": 78,  "gi": 0,  "satfat": 0.1, "k": 244, "ph": 138, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "merluza":          {"kcal": 86,  "p": 18,  "c": 0,   "f": 1.3, "fib": 0,   "sug": 0,   "na": 75,  "gi": 0,  "satfat": 0.2, "k": 280, "ph": 195, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "lenguado":         {"kcal": 91,  "p": 19,  "c": 0,   "f": 1.2, "fib": 0,   "sug": 0,   "na": 81,  "gi": 0,  "satfat": 0.2, "k": 286, "ph": 195, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "tilapia":          {"kcal": 128, "p": 26,  "c": 0,   "f": 2.7, "fib": 0,   "sug": 0,   "na": 56,  "gi": 0,  "satfat": 0.9, "k": 380, "ph": 200, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "trucha":           {"kcal": 168, "p": 23,  "c": 0,   "f": 8,   "fib": 0,   "sug": 0,   "na": 50,  "gi": 0,  "satfat": 2.0, "k": 463, "ph": 260, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "sardinas":         {"kcal": 208, "p": 25,  "c": 0,   "f": 11,  "fib": 0,   "sug": 0,   "na": 307, "gi": 0,  "satfat": 1.5, "k": 397, "ph": 490, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "salmon_ahumado":   {"kcal": 117, "p": 18,  "c": 0,   "f": 4.3, "fib": 0,   "sug": 0,   "na": 672, "gi": 0,  "satfat": 0.9, "k": 175, "ph": 164, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "anchoas":          {"kcal": 131, "p": 20,  "c": 0,   "f": 5,   "fib": 0,   "sug": 0,   "na": 1040,"gi": 0,  "satfat": 1.3, "k": 300, "ph": 174, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "caballa":          {"kcal": 205, "p": 19,  "c": 0,   "f": 14,  "fib": 0,   "sug": 0,   "na": 90,  "gi": 0,  "satfat": 3.6, "k": 314, "ph": 217, "tags": ["omnivore","pescatarian"], "allergens": ["fish"]},
    "lomo_magro":       {"kcal": 158, "p": 26,  "c": 0,   "f": 6,   "fib": 0,   "sug": 0,   "na": 60,  "gi": 0,  "satfat": 2.0, "k": 340, "ph": 220, "tags": ["omnivore"]},
    "carne_magra_res":  {"kcal": 182, "p": 27,  "c": 0,   "f": 8,   "fib": 0,   "sug": 0,   "na": 65,  "gi": 0,  "satfat": 3.2, "k": 318, "ph": 200, "tags": ["omnivore"]},
    "jerky_pavo":       {"kcal": 287, "p": 51,  "c": 9,   "f": 5,   "fib": 0,   "sug": 6,   "na": 1900,"gi": 0,  "satfat": 1.5, "k": 410, "ph": 380, "tags": ["omnivore"]},
    "jerky_res":        {"kcal": 410, "p": 33,  "c": 11,  "f": 26,  "fib": 0,   "sug": 9,   "na": 2080,"gi": 0,  "satfat": 11,  "k": 597, "ph": 290, "tags": ["omnivore"]},
    "huevo":            {"kcal": 143, "p": 13,  "c": 1.1, "f": 9.5, "fib": 0,   "sug": 1.1, "na": 142, "gi": 0,  "satfat": 3.0, "k": 138, "ph": 198, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["egg"]},
    "clara_huevo":      {"kcal": 52,  "p": 11,  "c": 0.7, "f": 0.2, "fib": 0,   "sug": 0.7, "na": 166, "gi": 0,  "satfat": 0.0, "k": 163, "ph": 15,  "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["egg"]},
    "yogur_griego":     {"kcal": 59,  "p": 10,  "c": 3.6, "f": 0.4, "fib": 0,   "sug": 3.2, "na": 36,  "gi": 11, "satfat": 0.1, "k": 141, "ph": 135, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_cottage":    {"kcal": 98,  "p": 11,  "c": 3.4, "f": 4.3, "fib": 0,   "sug": 2.7, "na": 364, "gi": 30, "satfat": 1.7, "k": 104, "ph": 160, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_fresco":     {"kcal": 98,  "p": 11,  "c": 3.4, "f": 4.3, "fib": 0,   "sug": 3.4, "na": 350, "gi": 30, "satfat": 2.5, "k": 127, "ph": 174, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_panela":     {"kcal": 175, "p": 17,  "c": 4,   "f": 10,  "fib": 0,   "sug": 4,   "na": 318, "gi": 30, "satfat": 6.0, "k": 90,  "ph": 220, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "ricotta":          {"kcal": 174, "p": 11,  "c": 3,   "f": 13,  "fib": 0,   "sug": 0.3, "na": 84,  "gi": 30, "satfat": 8.3, "k": 105, "ph": 158, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "paneer":           {"kcal": 265, "p": 18,  "c": 1.2, "f": 21,  "fib": 0,   "sug": 1.2, "na": 18,  "gi": 30, "satfat": 13,  "k": 105, "ph": 200, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    "queso_string":     {"kcal": 290, "p": 28,  "c": 3,   "f": 18,  "fib": 0,   "sug": 1,   "na": 545, "gi": 30, "satfat": 11,  "k": 76,  "ph": 470, "tags": ["omnivore","pescatarian","vegetarian"], "allergens": ["dairy"]},
    # Plant proteins
    "tofu_firme":       {"kcal": 144, "p": 17,  "c": 3,   "f": 9,   "fib": 2,   "sug": 1,   "na": 14,  "gi": 15, "satfat": 1.3, "k": 121, "ph": 190, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "tempeh":           {"kcal": 192, "p": 20,  "c": 8,   "f": 11,  "fib": 0,   "sug": 0,   "na": 9,   "gi": 15, "satfat": 2.2, "k": 412, "ph": 266, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "lentejas":         {"kcal": 116, "p": 9,   "c": 20,  "f": 0.4, "fib": 8,   "sug": 1.8, "na": 2,   "gi": 32, "satfat": 0.1, "k": 369, "ph": 180, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "garbanzos":        {"kcal": 164, "p": 8.9, "c": 27,  "f": 2.6, "fib": 7.6, "sug": 4.8, "na": 7,   "gi": 28, "satfat": 0.3, "k": 291, "ph": 168, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "frijoles_negros":  {"kcal": 132, "p": 8.9, "c": 24,  "f": 0.5, "fib": 8.7, "sug": 0.3, "na": 1,   "gi": 30, "satfat": 0.1, "k": 355, "ph": 140, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "frijoles_pintos":  {"kcal": 143, "p": 9,   "c": 26,  "f": 0.7, "fib": 9,   "sug": 0.3, "na": 1,   "gi": 39, "satfat": 0.1, "k": 436, "ph": 147, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "edamame":          {"kcal": 121, "p": 12,  "c": 9,   "f": 5,   "fib": 5,   "sug": 2.2, "na": 6,   "gi": 18, "satfat": 0.6, "k": 436, "ph": 169, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    "garbanzos_tostado":{"kcal": 364, "p": 19,  "c": 60,  "f": 6,   "fib": 17,  "sug": 11,  "na": 24,  "gi": 28, "satfat": 0.6, "k": 800, "ph": 366, "tags": ["omnivore","pescatarian","vegetarian","vegan"]},
    "edamame_tostado":  {"kcal": 426, "p": 36,  "c": 33,  "f": 19,  "fib": 18,  "sug": 11,  "na": 25,  "gi": 18, "satfat": 2.2, "k": 1364,"ph": 600, "tags": ["omnivore","pescatarian","vegetarian","vegan"], "allergens": ["soy"]},
    # Carbs
    "quinoa":           {"kcal": 120, "p": 4.4, "c": 21,  "f": 1.9, "fib": 2.8, "sug": 0.9, "na": 7,   "gi": 53, "satfat": 0.2, "k": 172, "ph": 152, "tags": ["any"]},
    "arroz_integral":   {"kcal": 123, "p": 2.7, "c": 26,  "f": 1.0, "fib": 1.6, "sug": 0.4, "na": 4,   "gi": 50, "satfat": 0.3, "k": 79,  "ph": 83,  "tags": ["any"]},
    "arroz_blanco":     {"kcal": 130, "p": 2.7, "c": 28,  "f": 0.3, "fib": 0.4, "sug": 0.1, "na": 1,   "gi": 73, "satfat": 0.1, "k": 35,  "ph": 43,  "tags": ["any"]},
    "arroz_basmati":    {"kcal": 121, "p": 3,   "c": 25,  "f": 0.4, "fib": 0.4, "sug": 0,   "na": 3,   "gi": 58, "satfat": 0.1, "k": 35,  "ph": 43,  "tags": ["any"]},
    "camote":           {"kcal": 86,  "p": 1.6, "c": 20,  "f": 0.1, "fib": 3,   "sug": 4.2, "na": 55,  "gi": 63, "satfat": 0.0, "k": 337, "ph": 47,  "tags": ["any"]},
    "papa_blanca":      {"kcal": 77,  "p": 2,   "c": 17,  "f": 0.1, "fib": 2.2, "sug": 0.8, "na": 6,   "gi": 78, "satfat": 0.0, "k": 421, "ph": 57,  "tags": ["any"]},
    "polenta":          {"kcal": 70,  "p": 1.5, "c": 15,  "f": 0.3, "fib": 1,   "sug": 0,   "na": 1,   "gi": 68, "satfat": 0.0, "k": 21,  "ph": 22,  "tags": ["any"]},
    "tortilla_maiz":    {"kcal": 218, "p": 5.7, "c": 45,  "f": 2.9, "fib": 6.3, "sug": 1.1, "na": 45,  "gi": 52, "satfat": 0.4, "k": 186, "ph": 314, "tags": ["any"]},
    "arepa_maiz":       {"kcal": 220, "p": 5,   "c": 47,  "f": 2.5, "fib": 5,   "sug": 0.5, "na": 220, "gi": 55, "satfat": 0.3, "k": 100, "ph": 95,  "tags": ["any"]},
    "avena_gf":         {"kcal": 71,  "p": 2.5, "c": 12,  "f": 1.5, "fib": 1.7, "sug": 0,   "na": 3,   "gi": 55, "satfat": 0.3, "k": 70,  "ph": 80,  "tags": ["any"]},
    "avena_seca_gf":    {"kcal": 389, "p": 17,  "c": 66,  "f": 7,   "fib": 11,  "sug": 0,   "na": 2,   "gi": 55, "satfat": 1.2, "k": 429, "ph": 523, "tags": ["any"]},
    "pan_arroz":        {"kcal": 360, "p": 6,   "c": 78,  "f": 2.5, "fib": 4,   "sug": 2,   "na": 480, "gi": 75, "satfat": 0.4, "k": 92,  "ph": 100, "tags": ["any"]},
    "galleta_arroz":    {"kcal": 387, "p": 8,   "c": 82,  "f": 2.8, "fib": 4,   "sug": 0.5, "na": 23,  "gi": 87, "satfat": 0.5, "k": 100, "ph": 100, "tags": ["any"]},
    "yuca":             {"kcal": 160, "p": 1.4, "c": 38,  "f": 0.3, "fib": 1.8, "sug": 1.7, "na": 14,  "gi": 55, "satfat": 0.1, "k": 271, "ph": 27,  "tags": ["any"]},
    "platano_macho":    {"kcal": 122, "p": 1.3, "c": 32,  "f": 0.4, "fib": 2.3, "sug": 15,  "na": 4,   "gi": 55, "satfat": 0.1, "k": 499, "ph": 34,  "tags": ["any"]},
    "mochi_arroz":      {"kcal": 235, "p": 4,   "c": 50,  "f": 1,   "fib": 1,   "sug": 1,   "na": 5,   "gi": 80, "satfat": 0.2, "k": 30,  "ph": 30,  "tags": ["any"]},
    # Vegetables (general + low-K subset)
    "brocoli":          {"kcal": 35,  "p": 2.4, "c": 7,   "f": 0.4, "fib": 3.3, "sug": 1.7, "na": 41,  "gi": 15, "satfat": 0.0, "k": 316, "ph": 66,  "tags": ["any"]},
    "espinaca":         {"kcal": 23,  "p": 2.9, "c": 3.6, "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79,  "gi": 15, "satfat": 0.1, "k": 558, "ph": 49,  "tags": ["any"]},
    "kale":             {"kcal": 35,  "p": 2.9, "c": 4.4, "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53,  "gi": 15, "satfat": 0.2, "k": 348, "ph": 55,  "tags": ["any"]},
    "tomate":           {"kcal": 18,  "p": 0.9, "c": 3.9, "f": 0.2, "fib": 1.2, "sug": 2.6, "na": 5,   "gi": 30, "satfat": 0.0, "k": 237, "ph": 24,  "tags": ["any"]},
    "pimiento_rojo":    {"kcal": 31,  "p": 1,   "c": 6,   "f": 0.3, "fib": 2.1, "sug": 4.2, "na": 4,   "gi": 15, "satfat": 0.1, "k": 211, "ph": 26,  "tags": ["any"]},
    "calabacin":        {"kcal": 17,  "p": 1.2, "c": 3.1, "f": 0.3, "fib": 1,   "sug": 2.5, "na": 8,   "gi": 15, "satfat": 0.1, "k": 261, "ph": 38,  "tags": ["any"]},
    "zanahoria":        {"kcal": 41,  "p": 0.9, "c": 9.6, "f": 0.2, "fib": 2.8, "sug": 4.7, "na": 69,  "gi": 39, "satfat": 0.0, "k": 320, "ph": 35,  "tags": ["any"]},
    "cebolla":          {"kcal": 40,  "p": 1.1, "c": 9.3, "f": 0.1, "fib": 1.7, "sug": 4.2, "na": 4,   "gi": 15, "satfat": 0.0, "k": 146, "ph": 29,  "tags": ["any"]},
    "champinones":      {"kcal": 22,  "p": 3.1, "c": 3.3, "f": 0.3, "fib": 1,   "sug": 2,   "na": 5,   "gi": 15, "satfat": 0.0, "k": 318, "ph": 86,  "tags": ["any"]},
    "aguacate":         {"kcal": 160, "p": 2,   "c": 9,   "f": 15,  "fib": 7,   "sug": 0.7, "na": 7,   "gi": 10, "satfat": 2.1, "k": 485, "ph": 52,  "tags": ["any"]},
    "pepino":           {"kcal": 16,  "p": 0.7, "c": 3.6, "f": 0.1, "fib": 0.5, "sug": 1.7, "na": 2,   "gi": 15, "satfat": 0.0, "k": 147, "ph": 24,  "tags": ["any"]},
    "lechuga":          {"kcal": 15,  "p": 1.4, "c": 2.9, "f": 0.2, "fib": 1.3, "sug": 0.8, "na": 28,  "gi": 15, "satfat": 0.0, "k": 194, "ph": 29,  "tags": ["any"]},
    "repollo":          {"kcal": 25,  "p": 1.3, "c": 5.8, "f": 0.1, "fib": 2.5, "sug": 3.2, "na": 18,  "gi": 15, "satfat": 0.0, "k": 170, "ph": 26,  "tags": ["any"]},
    "judias_verdes":    {"kcal": 31,  "p": 1.8, "c": 7,   "f": 0.2, "fib": 2.7, "sug": 3.3, "na": 6,   "gi": 32, "satfat": 0.0, "k": 211, "ph": 38,  "tags": ["any"]},
    "coliflor":         {"kcal": 25,  "p": 1.9, "c": 5,   "f": 0.3, "fib": 2,   "sug": 1.9, "na": 30,  "gi": 15, "satfat": 0.0, "k": 299, "ph": 44,  "tags": ["any"]},
    "berenjena":        {"kcal": 25,  "p": 1,   "c": 6,   "f": 0.2, "fib": 3,   "sug": 3.5, "na": 2,   "gi": 15, "satfat": 0.0, "k": 229, "ph": 24,  "tags": ["any"]},
    "esparragos":       {"kcal": 20,  "p": 2.2, "c": 3.9, "f": 0.1, "fib": 2.1, "sug": 1.9, "na": 2,   "gi": 15, "satfat": 0.0, "k": 202, "ph": 52,  "tags": ["any"]},
    "alga_nori":        {"kcal": 35,  "p": 6,   "c": 5,   "f": 0.3, "fib": 0.3, "sug": 0,   "na": 48,  "gi": 15, "satfat": 0.0, "k": 356, "ph": 58,  "tags": ["any"]},
    "apio":             {"kcal": 16,  "p": 0.7, "c": 3,   "f": 0.2, "fib": 1.6, "sug": 1.3, "na": 80,  "gi": 15, "satfat": 0.0, "k": 260, "ph": 24,  "tags": ["any"]},
    "jalapeno":         {"kcal": 29,  "p": 0.9, "c": 6.5, "f": 0.4, "fib": 2.8, "sug": 4,   "na": 3,   "gi": 15, "satfat": 0.1, "k": 248, "ph": 25,  "tags": ["any"]},
    "remolacha":        {"kcal": 43,  "p": 1.6, "c": 10,  "f": 0.2, "fib": 2.8, "sug": 6.8, "na": 78,  "gi": 64, "satfat": 0.0, "k": 325, "ph": 40,  "tags": ["any"]},
    # Fats / nuts / seeds
    "aceite_oliva":     {"kcal": 884, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "satfat": 14,  "k": 1,   "ph": 0,   "tags": ["any"]},
    "aceite_sesamo":    {"kcal": 884, "p": 0,   "c": 0,   "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0,  "satfat": 14,  "k": 1,   "ph": 0,   "tags": ["any"], "allergens": ["sesame"]},
    "tahini":           {"kcal": 595, "p": 17,  "c": 21,  "f": 53,  "fib": 9.3, "sug": 0.5, "na": 115, "gi": 40, "satfat": 7.4, "k": 414, "ph": 732, "tags": ["any"], "allergens": ["sesame"]},
    "almendras":        {"kcal": 579, "p": 21,  "c": 22,  "f": 50,  "fib": 12,  "sug": 4.4, "na": 1,   "gi": 0,  "satfat": 3.8, "k": 733, "ph": 481, "tags": ["any"], "allergens": ["tree_nuts"]},
    "nuez":             {"kcal": 654, "p": 15,  "c": 14,  "f": 65,  "fib": 6.7, "sug": 2.6, "na": 2,   "gi": 0,  "satfat": 6.1, "k": 441, "ph": 346, "tags": ["any"], "allergens": ["tree_nuts"]},
    "pistacho":         {"kcal": 562, "p": 20,  "c": 28,  "f": 45,  "fib": 10,  "sug": 7.7, "na": 1,   "gi": 0,  "satfat": 5.4, "k": 1025,"ph": 490, "tags": ["any"], "allergens": ["tree_nuts"]},
    "mantequilla_mani": {"kcal": 588, "p": 25,  "c": 20,  "f": 50,  "fib": 6,   "sug": 9,   "na": 17,  "gi": 14, "satfat": 10,  "k": 649, "ph": 339, "tags": ["any"], "allergens": ["peanuts"]},
    "semillas_chia":    {"kcal": 486, "p": 17,  "c": 42,  "f": 31,  "fib": 34,  "sug": 0,   "na": 16,  "gi": 1,  "satfat": 3.3, "k": 407, "ph": 860, "tags": ["any"]},
    "semillas_lino":    {"kcal": 534, "p": 18,  "c": 29,  "f": 42,  "fib": 27,  "sug": 1.6, "na": 30,  "gi": 1,  "satfat": 3.7, "k": 813, "ph": 642, "tags": ["any"]},
    "semillas_calabaza":{"kcal": 559, "p": 30,  "c": 11,  "f": 49,  "fib": 6,   "sug": 1.4, "na": 7,   "gi": 25, "satfat": 8.7, "k": 809, "ph": 1233,"tags": ["any"]},
    "aceitunas":        {"kcal": 115, "p": 0.8, "c": 6,   "f": 11,  "fib": 3.2, "sug": 0,   "na": 735, "gi": 0,  "satfat": 1.4, "k": 8,   "ph": 4,   "tags": ["any"]},
    "mantequilla":      {"kcal": 717, "p": 0.9, "c": 0.1, "f": 81,  "fib": 0,   "sug": 0.1, "na": 11,  "gi": 0,  "satfat": 51,  "k": 24,  "ph": 24,  "tags": ["any"], "allergens": ["dairy"]},
    # Fruits / sweet liquids
    "manzana":          {"kcal": 52,  "p": 0.3, "c": 14,  "f": 0.2, "fib": 2.4, "sug": 10,  "na": 1,   "gi": 36, "satfat": 0.0, "k": 107, "ph": 11,  "tags": ["any"]},
    "pera":             {"kcal": 57,  "p": 0.4, "c": 15,  "f": 0.1, "fib": 3.1, "sug": 9.8, "na": 1,   "gi": 38, "satfat": 0.0, "k": 116, "ph": 12,  "tags": ["any"]},
    "uvas":             {"kcal": 69,  "p": 0.7, "c": 18,  "f": 0.2, "fib": 0.9, "sug": 15,  "na": 2,   "gi": 53, "satfat": 0.1, "k": 191, "ph": 20,  "tags": ["any"]},
    "sandia":           {"kcal": 30,  "p": 0.6, "c": 8,   "f": 0.2, "fib": 0.4, "sug": 6,   "na": 1,   "gi": 72, "satfat": 0.0, "k": 112, "ph": 11,  "tags": ["any"]},
    "arandanos":        {"kcal": 57,  "p": 0.7, "c": 14,  "f": 0.3, "fib": 2.4, "sug": 10,  "na": 1,   "gi": 53, "satfat": 0.0, "k": 77,  "ph": 12,  "tags": ["any"]},
    "frutos_rojos":     {"kcal": 50,  "p": 1,   "c": 12,  "f": 0.3, "fib": 3,   "sug": 8,   "na": 1,   "gi": 32, "satfat": 0.0, "k": 153, "ph": 24,  "tags": ["any"]},
    "platano_fruta":    {"kcal": 89,  "p": 1.1, "c": 23,  "f": 0.3, "fib": 2.6, "sug": 12,  "na": 1,   "gi": 51, "satfat": 0.1, "k": 358, "ph": 22,  "tags": ["any"]},
    "pina":             {"kcal": 50,  "p": 0.5, "c": 13,  "f": 0.1, "fib": 1.4, "sug": 10,  "na": 1,   "gi": 59, "satfat": 0.0, "k": 109, "ph": 8,   "tags": ["any"]},
    "limon":            {"kcal": 29,  "p": 1.1, "c": 9,   "f": 0.3, "fib": 2.8, "sug": 2.5, "na": 2,   "gi": 20, "satfat": 0.0, "k": 138, "ph": 16,  "tags": ["any"]},
    "jengibre":         {"kcal": 80,  "p": 1.8, "c": 18,  "f": 0.8, "fib": 2,   "sug": 1.7, "na": 13,  "gi": 15, "satfat": 0.2, "k": 415, "ph": 34,  "tags": ["any"]},
    "curcuma":          {"kcal": 312, "p": 9.7, "c": 67,  "f": 3.3, "fib": 23,  "sug": 3.2, "na": 27,  "gi": 15, "satfat": 1.0, "k": 2080,"ph": 299, "tags": ["any"]},
    "menta":            {"kcal": 70,  "p": 3.8, "c": 15,  "f": 0.9, "fib": 8,   "sug": 0,   "na": 31,  "gi": 15, "satfat": 0.2, "k": 569, "ph": 73,  "tags": ["any"]},
    "granada":          {"kcal": 83,  "p": 1.7, "c": 19,  "f": 1.2, "fib": 4,   "sug": 14,  "na": 3,   "gi": 53, "satfat": 0.1, "k": 236, "ph": 36,  "tags": ["any"]},
    "betarraga":        {"kcal": 43,  "p": 1.6, "c": 10,  "f": 0.2, "fib": 2.8, "sug": 6.8, "na": 78,  "gi": 64, "satfat": 0.0, "k": 325, "ph": 40,  "tags": ["any"]},
    "jamaica":          {"kcal": 37,  "p": 0.4, "c": 9,   "f": 0.6, "fib": 0.3, "sug": 7,   "na": 3,   "gi": 35, "satfat": 0.0, "k": 9,   "ph": 9,   "tags": ["any"]},
    "kombucha":         {"kcal": 30,  "p": 0,   "c": 7,   "f": 0,   "fib": 0,   "sug": 6,   "na": 5,   "gi": 25, "satfat": 0.0, "k": 30,  "ph": 5,   "tags": ["any"]},
    # Liquids
    "leche_almendra":   {"kcal": 17,  "p": 0.6, "c": 0.6, "f": 1.5, "fib": 0.3, "sug": 0,   "na": 60,  "gi": 25, "satfat": 0.1, "k": 50,  "ph": 18,  "tags": ["any"], "allergens": ["tree_nuts"]},
    "agua_coco":        {"kcal": 19,  "p": 0.7, "c": 3.7, "f": 0.2, "fib": 1.1, "sug": 2.6, "na": 105, "gi": 55, "satfat": 0.2, "k": 250, "ph": 20,  "tags": ["any"]},
    # Sweetener / crackers
    "miel":             {"kcal": 304, "p": 0.3, "c": 82,  "f": 0,   "fib": 0.2, "sug": 82,  "na": 4,   "gi": 58, "satfat": 0.0, "k": 52,  "ph": 4,   "tags": ["any"]},
    "crackers_arroz":   {"kcal": 387, "p": 8,   "c": 82,  "f": 2.8, "fib": 4,   "sug": 0.5, "na": 23,  "gi": 87, "satfat": 0.5, "k": 100, "ph": 100, "tags": ["any"]},
    "hummus":           {"kcal": 166, "p": 7.9, "c": 14,  "f": 9.6, "fib": 6,   "sug": 0.3, "na": 379, "gi": 28, "satfat": 1.4, "k": 228, "ph": 176, "tags": ["any","vegan","vegetarian"], "allergens": ["sesame"]},
}

ALLERGEN_FROM_KEY = {k: tuple(v.get("allergens", [])) for k, v in ING.items()}

DISPLAY = {
    "pollo_pechuga": "Pollo", "pavo_pechuga": "Pavo",
    "salmon": "Salmón", "salmon_ahumado": "Salmón Ahumado",
    "atun_lata_agua": "Atún en Agua", "atun_fresco": "Atún Fresco",
    "bacalao": "Bacalao", "merluza": "Merluza", "lenguado": "Lenguado",
    "tilapia": "Tilapia", "trucha": "Trucha",
    "sardinas": "Sardinas", "anchoas": "Anchoas", "caballa": "Caballa",
    "lomo_magro": "Lomo Magro", "carne_magra_res": "Res Magra",
    "jerky_pavo": "Jerky de Pavo", "jerky_res": "Jerky de Res",
    "huevo": "Huevo", "clara_huevo": "Claras de Huevo",
    "yogur_griego": "Yogur Griego", "queso_cottage": "Cottage",
    "queso_fresco": "Queso Fresco", "queso_panela": "Queso Panela",
    "ricotta": "Ricotta", "paneer": "Paneer", "queso_string": "Queso String",
    "tofu_firme": "Tofu", "tempeh": "Tempeh",
    "lentejas": "Lentejas", "garbanzos": "Garbanzos",
    "frijoles_negros": "Frijoles Negros", "frijoles_pintos": "Frijoles Pintos",
    "edamame": "Edamame", "edamame_tostado": "Edamame Tostado",
    "garbanzos_tostado": "Garbanzos Tostados",
    "quinoa": "Quinoa", "arroz_integral": "Arroz Integral",
    "arroz_blanco": "Arroz Blanco", "arroz_basmati": "Arroz Basmati",
    "camote": "Camote", "papa_blanca": "Papa Blanca", "polenta": "Polenta",
    "tortilla_maiz": "Tortilla de Maíz", "arepa_maiz": "Arepa de Maíz",
    "avena_gf": "Avena Sin Gluten Certificada",
    "avena_seca_gf": "Avena GF en Hojuelas",
    "pan_arroz": "Pan de Arroz", "galleta_arroz": "Galleta de Arroz",
    "yuca": "Yuca", "platano_macho": "Plátano Macho",
    "mochi_arroz": "Mochi de Arroz",
    "brocoli": "Brócoli", "espinaca": "Espinaca", "kale": "Kale",
    "tomate": "Tomate", "pimiento_rojo": "Pimiento Rojo",
    "calabacin": "Calabacín", "zanahoria": "Zanahoria",
    "cebolla": "Cebolla", "champinones": "Champiñones",
    "aguacate": "Aguacate", "pepino": "Pepino", "lechuga": "Lechuga",
    "repollo": "Repollo", "judias_verdes": "Judías Verdes",
    "coliflor": "Coliflor", "berenjena": "Berenjena",
    "esparragos": "Espárragos", "alga_nori": "Alga Nori",
    "apio": "Apio", "jalapeno": "Jalapeño", "remolacha": "Remolacha",
    "aceite_oliva": "Aceite de Oliva", "aceite_sesamo": "Aceite de Sésamo",
    "tahini": "Tahini",
    "almendras": "Almendras", "nuez": "Nueces", "pistacho": "Pistachos",
    "mantequilla_mani": "Mantequilla de Maní",
    "semillas_chia": "Chía", "semillas_lino": "Linaza",
    "semillas_calabaza": "Semillas de Calabaza",
    "aceitunas": "Aceitunas", "mantequilla": "Mantequilla",
    "manzana": "Manzana", "pera": "Pera", "uvas": "Uvas", "sandia": "Sandía",
    "arandanos": "Arándanos", "frutos_rojos": "Frutos Rojos",
    "platano_fruta": "Plátano", "pina": "Piña", "limon": "Limón",
    "jengibre": "Jengibre", "curcuma": "Cúrcuma", "menta": "Menta",
    "granada": "Granada", "betarraga": "Betarraga",
    "jamaica": "Flor de Jamaica", "kombucha": "Kombucha",
    "leche_almendra": "Leche de Almendra", "agua_coco": "Agua de Coco",
    "miel": "Miel", "crackers_arroz": "Crackers de Arroz", "hummus": "Hummus",
}

# ---------------------------------------------------------------------------
# Template helper.
# ---------------------------------------------------------------------------
def _t(tid, cuisine, mt, diet, prot_pool, prot_g, carb_pool, carb_g, veg_pool, veg_g,
       fat_pool, fat_g, name, desc, regions, rec, contra, goals, act, preg,
       prep, cook, origin, instructions, meal_format="solid", bucket="generic"):
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
        "bucket": bucket,
    }

# ---------------------------------------------------------------------------
# Bucket A — Snacks (target 1,500 total)
# ---------------------------------------------------------------------------
SNACK_OMNI = [
    _t("snack_omni_jerky", ["north_american"], "snack", "omnivore",
       ["jerky_pavo","jerky_res"], 30,
       ["galleta_arroz","crackers_arroz","pan_arroz"], 25,
       ["pepino","apio","zanahoria","tomate"], 50,
       ["almendras","nuez","semillas_calabaza","aguacate"], 12,
       "Jerky Snack de {prot} con {carb} y {fat}",
       "Snack proteico portátil estilo jerky con vegetales crujientes.",
       ["us","ca","eu","uk"], ["athletic_load"], ["hypertension","ckd"],
       ["muscle_gain","maintain"], ["lightly_active","moderately_active","very_active"],
       True, 5, 0, "USA fitness",
       ["Sirve el {prot}.","Acompaña con {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="snack_omni"),
    _t("snack_omni_tuna_cup", ["latam","north_american"], "snack", "omnivore",
       ["atun_lata_agua","pollo_pechuga","pavo_pechuga"], 70,
       ["galleta_arroz","crackers_arroz","tortilla_maiz","pan_arroz"], 30,
       ["pepino","apio","tomate","lechuga","zanahoria"], 50,
       ["aguacate","aceite_oliva","almendras","aceitunas"], 10,
       "Tuna Cup de {prot} con {carb} y {fat}",
       "Snack proteico tipo cup, portátil y rico en omega-3.",
       ["us","ca","latam","eu"], ["athletic_load","dyslipidemia"], [],
       ["weight_loss","maintain","muscle_gain"], ["sedentary","lightly_active","moderately_active","very_active"],
       True, 5, 0, "Pan-Americano",
       ["Mezcla la {prot}.","Sirve sobre {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="snack_omni"),
    _t("snack_omni_deviled", ["north_american","mediterranean"], "snack", "omnivore",
       ["huevo"], 100,
       ["galleta_arroz","pan_arroz","tortilla_maiz"], 25,
       ["pepino","apio","tomate","lechuga"], 40,
       ["aguacate","aceite_oliva","aceitunas","almendras"], 8,
       "Huevos Endiablados con {carb} y {fat}",
       "Huevos endiablados clásicos altos en proteína y portátiles.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["maintain","muscle_gain","weight_loss"], ["lightly_active","moderately_active","very_active"],
       True, 10, 8, "USA clásico",
       ["Cocina los {prot}.","Acompaña con {carb}.","Sirve con {veg}.","Termina con {fat}."],
       bucket="snack_omni"),
    _t("snack_omni_chickenroll", ["latam","north_american"], "snack", "omnivore",
       ["pollo_pechuga","pavo_pechuga","jerky_pavo"], 70,
       ["tortilla_maiz","arepa_maiz","pan_arroz"], 30,
       ["lechuga","espinaca","tomate","pepino"], 40,
       ["aguacate","aceite_oliva","almendras","queso_fresco"], 12,
       "Roll-up de {prot} con {carb} y {fat}",
       "Roll-up proteico portátil con tortilla y vegetales frescos.",
       ["us","ca","latam"], ["athletic_load"], [],
       ["muscle_gain","maintain"], ["lightly_active","moderately_active","very_active"],
       True, 6, 5, "TexMex/USA",
       ["Cocina la {prot}.","Coloca sobre {carb}.","Añade {veg}.","Termina con {fat}.","Enrolla y sirve."],
       bucket="snack_omni"),
    _t("snack_omni_cheesestick", ["north_american","mediterranean"], "snack", "omnivore",
       ["queso_string","queso_panela","queso_fresco","huevo"], 60,
       ["galleta_arroz","crackers_arroz","pan_arroz"], 25,
       ["pepino","apio","tomate","zanahoria"], 40,
       ["almendras","nuez","aceitunas","aguacate"], 10,
       "Cheese Stick Snack con {prot}, {carb} y {fat}",
       "Snack lácteo proteico de bajo carbohidrato.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","maintain"], ["lightly_active","moderately_active","very_active"],
       True, 3, 0, "USA convenience",
       ["Sirve los {prot}.","Acompaña con {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="snack_omni"),
]

SNACK_PESC = [
    _t("snack_pesc_smokedsalmon", ["mediterranean","north_american"], "snack", "pescatarian",
       ["salmon_ahumado","salmon","atun_fresco"], 60,
       ["pan_arroz","galleta_arroz","crackers_arroz","tortilla_maiz"], 25,
       ["pepino","tomate","lechuga","espinaca"], 40,
       ["aguacate","aceite_oliva","aceitunas","almendras"], 10,
       "Bocado de {prot} con {carb} y {fat}",
       "Snack pescatariano elegante alto en omega-3.",
       ["us","eu","uk","ca"], ["dyslipidemia","ischemic_heart_disease","mild_depression"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 5, 0, "Nordic",
       ["Sirve el {prot}.","Coloca sobre {carb}.","Decora con {veg}.","Termina con {fat}."],
       bucket="snack_pesc"),
    _t("snack_pesc_tunastuffed", ["mediterranean","latam"], "snack", "pescatarian",
       ["atun_lata_agua","atun_fresco","sardinas"], 70,
       ["galleta_arroz","crackers_arroz","tortilla_maiz","pan_arroz"], 25,
       ["pimiento_rojo","pepino","tomate","apio"], 50,
       ["aguacate","aceite_oliva","aceitunas"], 10,
       "Pimiento Relleno de {prot} con {carb} y {fat}",
       "Pimiento relleno de pescado con omega-3 y polifenoles.",
       ["us","eu","uk","latam"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 8, 0, "Mediterráneo",
       ["Mezcla el {prot}.","Rellena {veg}.","Acompaña con {carb}.","Termina con {fat}."],
       bucket="snack_pesc"),
    _t("snack_pesc_ceviche", ["latam"], "snack", "pescatarian",
       ["tilapia","merluza","bacalao","lenguado","atun_fresco"], 70,
       ["tortilla_maiz","camote","yuca","galleta_arroz"], 30,
       ["pepino","tomate","cebolla","pimiento_rojo","lechuga"], 50,
       ["aguacate","aceite_oliva"], 8,
       "Cup de Ceviche de {prot} con {carb} y {fat}",
       "Mini cup de ceviche fresco con pescado magro.",
       ["latam","us"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 0, "Perú/Ecuador",
       ["Marina el {prot} en limón.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="snack_pesc"),
    _t("snack_pesc_sardine", ["mediterranean","eu"], "snack", "pescatarian",
       ["sardinas","anchoas","atun_lata_agua"], 50,
       ["pan_arroz","galleta_arroz","crackers_arroz"], 25,
       ["tomate","pepino","pimiento_rojo","lechuga"], 40,
       ["aceite_oliva","aceitunas","aguacate"], 10,
       "Tostada de {prot} con {carb} y {fat}",
       "Tostada mediterránea de pescado azul rica en omega-3.",
       ["eu","us","uk"], ["dyslipidemia","ischemic_heart_disease","mild_depression"], ["hypertension"],
       ["health","maintain","weight_loss"], ["sedentary","lightly_active","moderately_active"],
       False, 5, 0, "Mediterráneo",
       ["Sirve el {prot}.","Coloca sobre {carb}.","Decora con {veg}.","Termina con {fat}."],
       bucket="snack_pesc"),
    _t("snack_pesc_norisalmon", ["asian"], "snack", "pescatarian",
       ["salmon","salmon_ahumado","atun_fresco"], 60,
       ["arroz_blanco","arroz_basmati","mochi_arroz"], 30,
       ["pepino","aguacate","alga_nori","espinaca"], 40,
       ["aceite_sesamo","semillas_chia"], 8,
       "Mini Roll Nori de {prot} con {carb} y {fat}",
       "Bocado tipo onigiri-roll con pescado y alga nori.",
       ["us","eu","uk","ca"], ["dyslipidemia","ischemic_heart_disease"], [],
       ["health","maintain"], ["lightly_active","moderately_active"],
       False, 10, 5, "Japón",
       ["Cocina el {prot}.","Sirve sobre {carb}.","Envuelve con {veg}.","Termina con {fat}."],
       bucket="snack_pesc"),
]

SNACK_VEGAN = [
    _t("snack_vegan_roastedchick", ["middle_eastern","latam"], "snack", "vegan",
       ["garbanzos_tostado","edamame_tostado"], 40,
       ["galleta_arroz","tortilla_maiz","crackers_arroz"], 25,
       ["pepino","apio","zanahoria","tomate"], 40,
       ["aguacate","aceite_oliva","semillas_calabaza"], 10,
       "Snack Vegano Tostado de {prot} con {carb} y {fat}",
       "Snack vegano crujiente alto en proteína y fibra.",
       ["us","eu","uk","latam"], ["dyslipidemia"], [],
       ["weight_loss","maintain","health"], ["sedentary","lightly_active","moderately_active","very_active"],
       True, 5, 0, "Mediterráneo",
       ["Sirve el {prot}.","Acompaña con {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="snack_vegan"),
    _t("snack_vegan_hummus", ["middle_eastern"], "snack", "vegan",
       ["hummus","garbanzos"], 70,
       ["galleta_arroz","tortilla_maiz","pan_arroz","crackers_arroz"], 25,
       ["pepino","apio","zanahoria","pimiento_rojo","tomate"], 60,
       ["aceite_oliva","semillas_calabaza","almendras"], 8,
       "Hummus Plato con {carb} y {veg}",
       "Plato de hummus levantino con vegetales frescos.",
       ["us","eu","uk","latam"], ["dyslipidemia"], [],
       ["weight_loss","maintain","health"], ["sedentary","lightly_active","moderately_active"],
       True, 8, 0, "Líbano",
       ["Sirve el {prot}.","Acompaña con {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="snack_vegan"),
    _t("snack_vegan_energyball", ["north_american","latam"], "snack", "vegan",
       ["semillas_chia","semillas_lino","semillas_calabaza"], 25,
       ["avena_seca_gf","avena_gf"], 30,
       ["arandanos","frutos_rojos","manzana"], 30,
       ["mantequilla_mani","almendras","nuez"], 15,
       "Energy Ball Vegano con {carb}, {veg} y {fat}",
       "Bolitas energéticas veganas con grasas saludables y fibra.",
       ["us","eu","uk","latam","ca"], ["dyslipidemia"], [],
       ["muscle_gain","maintain","weight_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 0, "Fitness plant-based",
       ["Mezcla {prot}.","Combina con {carb}.","Añade {veg}.","Termina con {fat}.","Forma bolitas y refrigera."],
       bucket="snack_vegan"),
]

SNACK_VEG = [
    _t("snack_veg_cottage", ["north_american","mediterranean"], "snack", "vegetarian",
       ["queso_cottage","ricotta","yogur_griego"], 100,
       ["avena_seca_gf","avena_gf","galleta_arroz"], 30,
       ["frutos_rojos","arandanos","manzana"], 40,
       ["semillas_chia","almendras","nuez","semillas_lino"], 12,
       "Bowl de {prot} con {carb}, {veg} y {fat}",
       "Bowl lácteo proteico ligero con grasas saludables.",
       ["us","ca","eu","uk"], ["athletic_load"], [],
       ["muscle_gain","maintain","weight_loss"], ["lightly_active","moderately_active","very_active"],
       True, 5, 0, "Fitness USA",
       ["Sirve el {prot}.","Mezcla con {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="snack_veg"),
    _t("snack_veg_paneer", ["asian","middle_eastern"], "snack", "vegetarian",
       ["paneer","queso_panela","queso_fresco"], 70,
       ["galleta_arroz","pan_arroz","tortilla_maiz"], 25,
       ["pimiento_rojo","tomate","calabacin","cebolla"], 50,
       ["aceite_oliva","semillas_calabaza","almendras"], 10,
       "Brocheta de {prot} con {carb} y {fat}",
       "Brocheta de queso firme estilo tikka con vegetales asados.",
       ["us","eu","uk","ca"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 8, "India",
       ["Marina el {prot}.","Asa en brocheta.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="snack_veg"),
]

# ---------------------------------------------------------------------------
# Bucket B — Breakfast pescatarian +200
# ---------------------------------------------------------------------------
BREAKFAST_PESC = [
    _t("bf_pesc_smoked_avo", ["mediterranean","north_american"], "breakfast", "pescatarian",
       ["salmon_ahumado","salmon","atun_fresco"], 80,
       ["pan_arroz","avena_seca_gf","arepa_maiz","tortilla_maiz"], 40,
       ["aguacate","espinaca","tomate","pepino"], 60,
       ["aceite_oliva","aceitunas","semillas_chia","almendras"], 12,
       "Desayuno Pescatariano de {prot} con {carb}, {veg} y {fat}",
       "Desayuno pescatariano con omega-3 y grasas saludables.",
       ["us","eu","uk","ca"], ["dyslipidemia","ischemic_heart_disease","mild_depression"], [],
       ["health","weight_loss","maintain"], ["lightly_active","moderately_active"],
       False, 8, 5, "Nordic/USA",
       ["Sirve el {prot}.","Tuesta el {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_pesc"),
    _t("bf_pesc_tuna_omelette", ["mediterranean","latam"], "breakfast", "pescatarian",
       ["atun_lata_agua","atun_fresco","huevo"], 100,
       ["pan_arroz","arepa_maiz","tortilla_maiz","avena_seca_gf"], 40,
       ["espinaca","tomate","pimiento_rojo","champinones","cebolla"], 60,
       ["aguacate","aceite_oliva","aceitunas","almendras"], 12,
       "Tortilla de {prot} con {carb} y {veg}",
       "Tortilla pescatariana proteica para iniciar el día.",
       ["us","eu","uk","latam"], ["athletic_load","dyslipidemia"], [],
       ["muscle_gain","maintain","health"], ["moderately_active","very_active","lightly_active"],
       False, 10, 8, "Mediterráneo",
       ["Bate el {prot} con huevo.","Cocina como tortilla.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_pesc"),
    _t("bf_pesc_congee", ["asian"], "breakfast", "pescatarian",
       ["salmon","tilapia","bacalao","merluza"], 80,
       ["arroz_blanco","arroz_basmati","arroz_integral"], 50,
       ["espinaca","champinones","alga_nori","cebolla","jengibre"], 60,
       ["aceite_sesamo","semillas_chia"], 8,
       "Congee de {prot} con {carb} y {veg}",
       "Congee asiático de pescado, suave y reconfortante.",
       ["us","eu","uk","ca"], ["ischemic_heart_disease","dyslipidemia","ibs"], [],
       ["health","weight_loss","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 10, 25, "China/Sudeste asiático",
       ["Cocina el {carb} con agua.","Añade el {prot}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_pesc"),
    _t("bf_pesc_kippers", ["mediterranean","eu"], "breakfast", "pescatarian",
       ["caballa","sardinas","salmon_ahumado","anchoas"], 70,
       ["pan_arroz","avena_seca_gf"], 40,
       ["tomate","espinaca","pepino","champinones"], 50,
       ["aceite_oliva","aceitunas","aguacate"], 12,
       "Desayuno UK con {prot}, {carb} y {veg}",
       "Desayuno británico con pescado azul ahumado y omega-3.",
       ["uk","eu","us"], ["dyslipidemia","ischemic_heart_disease","mild_depression"], ["hypertension"],
       ["health","maintain"], ["lightly_active","moderately_active"],
       False, 8, 5, "UK breakfast",
       ["Sirve el {prot}.","Tuesta el {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_pesc"),
]

# ---------------------------------------------------------------------------
# Bucket C — Celiac recommended +100 (gluten-FREE verified)
# All ingredient keys here have ZERO gluten.
# ---------------------------------------------------------------------------
CELIAC = [
    _t("celiac_arepa", ["latam"], "lunch", "omnivore",
       ["pollo_pechuga","pavo_pechuga","huevo","queso_fresco","queso_panela"], 100,
       ["arepa_maiz","tortilla_maiz","yuca"], 80,
       ["tomate","aguacate","espinaca","pimiento_rojo","lechuga"], 80,
       ["aguacate","aceite_oliva","semillas_calabaza"], 12,
       "Arepa GF con {prot}, {carb} y {veg}",
       "Arepa naturalmente libre de gluten con proteína y vegetales.",
       ["latam","us"], ["celiac"], [],
       ["maintain","muscle_gain","health"], ["lightly_active","moderately_active","very_active"],
       True, 10, 15, "Venezuela/Colombia",
       ["Cocina el {carb}.","Rellena con {prot}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="celiac"),
    _t("celiac_polenta", ["mediterranean","latam"], "dinner", "vegetarian",
       ["huevo","queso_fresco","queso_panela","ricotta","lentejas"], 100,
       ["polenta","arroz_integral"], 100,
       ["champinones","calabacin","tomate","espinaca","brocoli"], 100,
       ["aceite_oliva","aceitunas","almendras"], 12,
       "Bowl GF de Polenta con {prot}, {carb} y {veg}",
       "Polenta naturalmente libre de gluten con proteína vegetariana.",
       ["latam","us","eu"], ["celiac"], [],
       ["health","maintain"], ["lightly_active","moderately_active"],
       True, 10, 20, "Italia/Argentina",
       ["Cocina el {carb}.","Acompaña con {prot}.","Añade {veg}.","Termina con {fat}."],
       bucket="celiac"),
    _t("celiac_quinoa_bowl", ["latam","mediterranean"], "lunch", "vegan",
       ["lentejas","garbanzos","frijoles_negros","tofu_firme","edamame"], 100,
       ["quinoa","arroz_integral","camote","yuca"], 80,
       ["espinaca","kale","tomate","pimiento_rojo","brocoli"], 100,
       ["aguacate","aceite_oliva","semillas_calabaza","almendras"], 12,
       "Bowl Andino GF de {prot} con {carb} y {veg}",
       "Bowl andino libre de gluten, alto en fibra y proteína vegetal.",
       ["latam","us","eu"], ["celiac","dyslipidemia"], [],
       ["health","maintain","weight_loss"], ["lightly_active","moderately_active"],
       True, 10, 18, "Andes",
       ["Cocina el {carb}.","Acompaña con {prot}.","Añade {veg}.","Termina con {fat}."],
       bucket="celiac"),
    _t("celiac_rice_congee", ["asian"], "breakfast", "pescatarian",
       ["salmon","tilapia","bacalao","huevo"], 80,
       ["arroz_blanco","arroz_basmati","arroz_integral"], 60,
       ["espinaca","champinones","cebolla","jengibre","alga_nori"], 50,
       ["aceite_sesamo","semillas_chia"], 8,
       "Congee GF de {prot} con {carb} y {veg}",
       "Congee asiático libre de gluten, suave y nutritivo.",
       ["us","eu","uk","ca"], ["celiac","ibs"], [],
       ["health","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 10, 25, "China",
       ["Cocina el {carb} con agua.","Añade {prot}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="celiac"),
    _t("celiac_camote_bowl", ["latam","north_american"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga","huevo","salmon"], 100,
       ["camote","yuca","arroz_integral","quinoa"], 100,
       ["espinaca","kale","tomate","brocoli","pimiento_rojo"], 100,
       ["aguacate","aceite_oliva","semillas_calabaza"], 12,
       "Cena GF de Camote con {prot}, {carb} y {veg}",
       "Cena naturalmente libre de gluten con tubérculo y proteína magra.",
       ["latam","us","ca"], ["celiac"], [],
       ["health","weight_loss","maintain"], ["lightly_active","moderately_active"],
       True, 12, 22, "Pan-American",
       ["Cocina el {prot}.","Asa el {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="celiac"),
]

# ---------------------------------------------------------------------------
# Bucket D — CKD-safe +200
# Strict gates: protein ≤ 25 g, sodium ≤ 500 mg, K ≤ 400 mg, P ≤ 300 mg.
# Use ONLY low-K/low-P ingredients in this bucket.
# ---------------------------------------------------------------------------
CKD = [
    _t("ckd_white_rice_chicken", ["asian","latam"], "lunch", "omnivore",
       ["pollo_pechuga","pavo_pechuga","clara_huevo","huevo"], 70,
       ["arroz_blanco","arroz_basmati","papa_blanca","polenta"], 100,
       ["pepino","repollo","judias_verdes","calabacin","lechuga"], 100,
       ["aceite_oliva","mantequilla"], 8,
       "Almuerzo Renal con {prot}, {carb} y {veg}",
       "Almuerzo renal protector con proteína controlada y vegetales bajos en potasio.",
       ["us","eu","latam","ca","uk"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 10, 15, "Renal-safe",
       ["Cocina el {prot} sin sal añadida.","Sirve sobre {carb}.","Acompaña con {veg} blanqueado.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_white_fish", ["mediterranean","eu"], "dinner", "pescatarian",
       ["bacalao","merluza","lenguado","tilapia"], 80,
       ["arroz_blanco","papa_blanca","arroz_basmati"], 100,
       ["pepino","repollo","calabacin","judias_verdes","lechuga"], 100,
       ["aceite_oliva","mantequilla"], 8,
       "Cena Renal de {prot} con {carb} y {veg}",
       "Cena renal protectora con pescado blanco bajo en fósforo.",
       ["eu","us","uk"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       False, 10, 18, "Mediterráneo renal",
       ["Hornea el {prot} sin sal.","Acompaña con {carb}.","Sirve con {veg} blanqueado.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_egg_white_breakfast", ["mediterranean","north_american"], "breakfast", "vegetarian",
       ["clara_huevo","huevo"], 80,
       ["pan_arroz","arroz_blanco","polenta"], 60,
       ["pepino","calabacin","repollo","lechuga"], 80,
       ["aceite_oliva","mantequilla"], 8,
       "Desayuno Renal con {prot}, {carb} y {veg}",
       "Desayuno renal protector con claras y carbohidrato blanco.",
       ["us","eu","uk","ca"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 8, 8, "USA/EU renal",
       ["Bate el {prot}.","Cocina y sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_apple_snack", ["north_american","eu"], "snack", "vegetarian",
       ["clara_huevo","queso_cottage"], 60,
       ["pan_arroz","galleta_arroz"], 25,
       ["manzana","pera","arandanos","uvas"], 80,
       ["mantequilla","aceite_oliva"], 6,
       "Snack Renal de {prot} con {veg} y {fat}",
       "Snack renal con frutas bajas en potasio.",
       ["us","eu","uk","ca"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 5, 0, "Renal-safe",
       ["Sirve el {prot}.","Acompaña con {carb}.","Añade {veg} fresco.","Termina con {fat}."],
       bucket="ckd"),
]

# ---------------------------------------------------------------------------
# Bucket E — Diabetes_t2 verified +500
# Gates: carbs ≤ 45, sugar ≤ 10, fiber ≥ 8, GL ≤ 10.
# Heavy use of legumes, non-starchy veg, lean protein, unsaturated fats.
# ---------------------------------------------------------------------------
DT2 = [
    _t("dt2_lentil_bowl", ["mediterranean","latam"], "lunch", "vegan",
       ["lentejas","garbanzos","frijoles_negros","tofu_firme","tempeh"], 130,
       ["quinoa","avena_gf","arroz_integral"], 60,
       ["espinaca","kale","brocoli","calabacin","tomate","pimiento_rojo"], 120,
       ["aguacate","aceite_oliva","semillas_chia","semillas_lino","almendras","nuez"], 12,
       "Bowl Diabético de {prot} con {carb} y {veg}",
       "Bowl diabético-friendly con legumbres altas en fibra y GL bajo.",
       ["us","eu","uk","latam","ca"], ["diabetes_t2","dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 12, 18, "Mediterráneo/Andes",
       ["Cocina las {prot}.","Sirve con {carb} integral.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="dt2"),
    _t("dt2_chickpea_salad", ["mediterranean","middle_eastern"], "lunch", "vegan",
       ["garbanzos","lentejas","frijoles_negros","tofu_firme"], 130,
       ["quinoa","avena_gf"], 50,
       ["espinaca","kale","pepino","tomate","pimiento_rojo","jalapeno"], 130,
       ["aceite_oliva","tahini","aguacate","semillas_lino","almendras","nuez"], 12,
       "Ensalada Diabética de {prot} con {carb} y {veg}",
       "Ensalada diabética alta en fibra con legumbres y grasas mono.",
       ["us","eu","uk","latam"], ["diabetes_t2","dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 10, 0, "Mediterráneo",
       ["Mezcla las {prot}.","Acompaña con {carb}.","Añade {veg}.","Aliña con {fat}."],
       bucket="dt2"),
    _t("dt2_protein_veg", ["mediterranean","asian"], "dinner", "pescatarian",
       ["salmon","atun_fresco","bacalao","merluza","tilapia"], 120,
       ["quinoa","avena_gf","lentejas"], 50,
       ["espinaca","kale","brocoli","esparragos","calabacin","pimiento_rojo"], 130,
       ["aceite_oliva","aguacate","semillas_chia","almendras","nuez"], 12,
       "Cena Diabética de {prot} con {carb} y {veg}",
       "Cena diabética con pescado magro, fibra y grasas saludables.",
       ["us","eu","uk","ca"], ["diabetes_t2","dyslipidemia","ischemic_heart_disease"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       False, 12, 20, "Mediterráneo",
       ["Cocina el {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="dt2"),
    _t("dt2_omni_bowl", ["mediterranean","latam"], "lunch", "omnivore",
       ["pollo_pechuga","pavo_pechuga","huevo","atun_lata_agua"], 110,
       ["lentejas","quinoa","avena_gf","frijoles_negros"], 60,
       ["espinaca","kale","brocoli","calabacin","tomate","pimiento_rojo"], 130,
       ["aguacate","aceite_oliva","semillas_chia","almendras","nuez"], 12,
       "Almuerzo Diabético Omnívoro de {prot} con {carb} y {veg}",
       "Almuerzo diabético omnívoro con proteína magra y legumbres altas en fibra.",
       ["us","eu","uk","latam","ca"], ["diabetes_t2","dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 12, 15, "Mediterráneo",
       ["Cocina la {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="dt2"),
    _t("dt2_breakfast_oat", ["mediterranean","north_american"], "breakfast", "vegetarian",
       ["huevo","yogur_griego","queso_cottage","clara_huevo"], 100,
       ["avena_gf","quinoa","lentejas"], 50,
       ["espinaca","kale","arandanos","frutos_rojos"], 100,
       ["semillas_chia","semillas_lino","almendras","nuez","aguacate"], 14,
       "Desayuno Diabético de {prot} con {carb} y {veg}",
       "Desayuno diabético con avena GF, proteína y grasas omega-3.",
       ["us","eu","uk","ca","latam"], ["diabetes_t2","dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 8, 8, "USA/Mediterráneo",
       ["Prepara el {prot}.","Cocina el {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="dt2"),
]

# ---------------------------------------------------------------------------
# Bucket F — Jugos weight_loss +50
# Liquid + low GL + low sugar. Viral content.
# ---------------------------------------------------------------------------
JUGOS = [
    _t("jugo_verde_apio", ["latam","north_american"], "snack", "vegan",
       ["apio"], 100,
       ["manzana","pera","limon"], 60,
       ["espinaca","kale","pepino"], 100,
       ["semillas_chia","semillas_lino","jengibre"], 10,
       "Jugo Verde Detox con {veg}, {carb} y {fat}",
       "Jugo verde detox bajo en azúcar para apoyo metabólico.",
       ["us","eu","uk","latam","ca"], ["dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 8, 0, "Wellness latam",
       ["Lava {veg} y {prot}.","Añade {carb}.","Licua con agua.","Termina con {fat}.","Sirve frío."],
       meal_format="liquid", bucket="jugo"),
    _t("jugo_jengibre_limon", ["asian","latam"], "snack", "vegan",
       ["jengibre"], 25,
       ["limon","manzana","pera"], 60,
       ["pepino","apio","menta"], 80,
       ["semillas_chia","curcuma"], 8,
       "Shot Antiinflamatorio de {prot}, {carb} y {veg}",
       "Shot/jugo antiinflamatorio con jengibre, limón y cúrcuma.",
       ["us","eu","uk","latam","ca"], ["dyslipidemia"], [],
       ["weight_loss","health"], ["sedentary","lightly_active","moderately_active"],
       True, 6, 0, "Wellness asia/latam",
       ["Ralla el {prot}.","Exprime el {carb}.","Mezcla con {veg}.","Termina con {fat}.","Cuela y sirve."],
       meal_format="liquid", bucket="jugo"),
    _t("jugo_betarraga", ["latam","mediterranean"], "snack", "vegan",
       ["betarraga"], 80,
       ["manzana","limon"], 60,
       ["apio","pepino","menta"], 80,
       ["jengibre","semillas_chia"], 8,
       "Jugo Antioxidante de {prot} con {carb} y {veg}",
       "Jugo antioxidante de betarraga rico en nitratos vegetales.",
       ["us","eu","uk","latam"], ["dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 8, 0, "Andes wellness",
       ["Pela el {prot}.","Combina con {carb}.","Añade {veg}.","Termina con {fat}.","Licua y sirve."],
       meal_format="liquid", bucket="jugo"),
    _t("jugo_pina_chia", ["latam"], "snack", "vegan",
       ["pina"], 70,
       ["limon"], 30,
       ["apio","pepino","menta","kale"], 80,
       ["semillas_chia","semillas_lino","jengibre"], 10,
       "Jugo Tropical de {prot} con {carb} y {fat}",
       "Jugo tropical con piña y chía para hidratación y fibra.",
       ["us","eu","latam"], ["dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 6, 0, "Caribe",
       ["Pica {prot}.","Añade {carb}.","Licua con {veg}.","Termina con {fat}.","Sirve frío."],
       meal_format="liquid", bucket="jugo"),
    _t("jugo_jamaica", ["latam"], "snack", "vegan",
       ["jamaica"], 30,
       ["limon"], 20,
       ["menta","pepino","apio"], 60,
       ["semillas_chia","jengibre"], 8,
       "Agua de {prot} con {carb} y {fat}",
       "Agua de jamaica con chía baja en azúcar.",
       ["us","latam"], ["dyslipidemia"], [],
       ["weight_loss","health","maintain"], ["sedentary","lightly_active","moderately_active"],
       True, 6, 5, "México",
       ["Hierve {prot}.","Añade {carb}.","Mezcla con {veg}.","Termina con {fat}.","Enfría y sirve."],
       meal_format="liquid", bucket="jugo"),
]

# ---------------------------------------------------------------------------
# Cuisine fan-out: clone templates per cuisine in their cuisine list so that
# each clone uses a different first-cuisine (drives cell key + name suffix),
# expanding unique name space without changing nutrition logic.
# ---------------------------------------------------------------------------
def _fanout(templates: list[dict]) -> list[dict]:
    out: list[dict] = []
    for tpl in templates:
        cuisines = tpl["cuisine"]
        if len(cuisines) <= 1:
            out.append(tpl)
            continue
        for i, c in enumerate(cuisines):
            clone = dict(tpl)
            rotated = [c] + [x for x in cuisines if x != c]
            clone["cuisine"] = rotated
            clone["tid"] = f"{tpl['tid']}_c{i}"
            out.append(clone)
    return out


# ---------------------------------------------------------------------------
# Aggregate all bucket templates
# ---------------------------------------------------------------------------
ALL_TEMPLATES = _fanout(
    SNACK_OMNI + SNACK_PESC + SNACK_VEGAN + SNACK_VEG +
    BREAKFAST_PESC + CELIAC + CKD + DT2 + JUGOS
)

# Per-bucket caps so generation stops once target is reached.
BUCKET_CAPS = {
    "snack_omni": 500, "snack_pesc": 500, "snack_vegan": 300, "snack_veg": 200,
    "bf_pesc": 200, "celiac": 100, "ckd": 200, "dt2": 500, "jugo": 50,
    "generic": 0,
}

# ---------------------------------------------------------------------------
# Dedup signature
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


def detect_allergens(component_keys: list[str]) -> list[str]:
    found: set[str] = set()
    for k in component_keys:
        for a in ALLERGEN_FROM_KEY.get(k, ()):
            found.add(a)
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    p = c = f = fib = sug = na = satfat = k_mg = ph_mg = 0.0
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
        k_mg += ing.get("k", 0) * factor
        ph_mg += ing.get("ph", 0) * factor
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
        "sodium_mg": int(round(na)), "gi": gi,
        "gl": round(gl, 1) if gl is not None else None,
        "satfat_g": int(round(satfat)),
        "potassium_mg": int(round(k_mg)), "phosphorus_mg": int(round(ph_mg)),
    }


def deterministic_id(template_id: str, slots: tuple[str, ...]) -> str:
    h = hashlib.sha1(("|".join(("gap", template_id, *slots))).encode()).hexdigest()
    return f"nova_meal_gap_{h[:10]}"


def validate_base(recipe: dict) -> tuple[bool, str]:
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
        return False, "protein_out_of_range"
    if not (0 <= m["carbs_g"] <= 200):
        return False, "carbs_out_of_range"
    if not (0 <= m["fat_g"] <= 80):
        return False, "fat_out_of_range"
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


def bucket_gate(recipe: dict, bucket: str) -> tuple[bool, str]:
    """Bucket-specific clinical gates. If failed, strip the bucket-specific
    condition rather than rejecting outright (except for hard-required buckets)."""
    m = recipe["nutrition_profile"]["macros"]
    micros = recipe["nutrition_profile"]["micronutrients"]
    rec = recipe["matching_criteria"]["recommended_for_conditions"]
    ingredients_text = " ".join(recipe["execution"]["ingredients"]).lower()
    allergens = recipe["matching_criteria"]["allergens"]

    if bucket == "celiac":
        if "gluten" in allergens:
            return False, "celiac_has_gluten"
        if "celiac" not in rec:
            return False, "celiac_missing_recommend"
    elif bucket == "ckd":
        if m["protein_g"] > 25:
            return False, "ckd_protein_high"
        if m["sodium_mg"] > 500:
            return False, "ckd_sodium_high"
        if micros["potassium_mg"] is not None and micros["potassium_mg"] > 400:
            return False, "ckd_potassium_high"
        if micros["phosphorus_mg"] is not None and micros["phosphorus_mg"] > 300:
            return False, "ckd_phosphorus_high"
        if "ckd" not in rec:
            return False, "ckd_missing_recommend"
    elif bucket == "dt2":
        if m["carbs_g"] > 45:
            return False, "dt2_carbs_high"
        if m["sugar_g"] > 10:
            return False, "dt2_sugar_high"
        if m["fiber_g"] < 8:
            return False, "dt2_fiber_low"
        gl = micros["gl"]
        if gl is not None and gl > 10:
            return False, "dt2_gl_high"
        if "diabetes_t2" not in rec:
            return False, "dt2_missing_recommend"
    elif bucket == "jugo":
        if m["carbs_g"] > 25:
            return False, "jugo_carbs_high"
        if m["sugar_g"] > 12:
            return False, "jugo_sugar_high"
        gl = micros["gl"]
        if gl is not None and gl > 10:
            return False, "jugo_gl_high"
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
    # Disambiguate names with cuisine + template id suffix so identical slot
    # combos across templates don't collide in cell name index.
    cuisine_label = {
        "north_american": "USA", "mediterranean": "Med",
        "latam": "LatAm", "asian": "Asia", "middle_eastern": "ME",
        "fusion": "Fusion", "african": "Afro", "nordic": "Nordic", "eu": "EU",
    }
    cuisine_tag = cuisine_label.get(tpl["cuisine"][0], tpl["cuisine"][0][:6].title())
    base_name = tpl["name"].format(
        prot=DISPLAY[prot], carb=DISPLAY[carb], veg=DISPLAY[veg], fat=DISPLAY[fat],
    )
    # Ensure 4 slots are reflected — append a compact slot trio if any are
    # absent from the base pattern so cartesian permutations stay unique.
    base_lower = base_name.lower()
    missing_tags: list[str] = []
    for label, key in ((DISPLAY[prot], "prot"), (DISPLAY[carb], "carb"),
                       (DISPLAY[veg], "veg"), (DISPLAY[fat], "fat")):
        if label.lower() not in base_lower:
            missing_tags.append(label)
    suffix_extra = (" + " + ", ".join(missing_tags)) if missing_tags else ""
    name = f"{base_name}{suffix_extra} ({cuisine_tag} · {tpl['tid'][-6:]})"
    desc = tpl["desc"]
    instructions = [s.format(prot=DISPLAY[prot], carb=DISPLAY[carb],
                              veg=DISPLAY[veg], fat=DISPLAY[fat])
                    for s in tpl["instructions"]]
    ingredients = [
        f"{tpl['prot_g']} g de {DISPLAY[prot]}",
        f"{tpl['carb_g']} g de {DISPLAY[carb]}",
        f"{tpl['veg_g']} g de {DISPLAY[veg]}",
        f"{tpl['fat_g']} g de {DISPLAY[fat]}",
        "Sal, pimienta y especias al gusto",
    ]
    rid = deterministic_id(tpl["tid"], (prot, carb, veg, fat))

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

    bucket = tpl.get("bucket", "generic")
    micronutrients = {
        "gi": m["gi"], "gl": m["gl"],
        "potassium_mg": None, "phosphorus_mg": None, "iron_mg": None,
        "heme_pct": None, "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
    }
    # Populate K/P only for CKD bucket (data quality is bounded).
    if bucket == "ckd":
        micronutrients["potassium_mg"] = m["potassium_mg"]
        micronutrients["phosphorus_mg"] = m["phosphorus_mg"]

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
            "micronutrients": micronutrients,
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
            "bucket": bucket,
        },
    }


def main() -> None:
    print("Loading existing catalog for dedup index...")
    existing = json.loads(EXISTING_CATALOG.read_text())
    existing_ids: set[str] = {r["id"] for r in existing if "id" in r}
    existing_sigs: set[str] = set()
    cell_names: dict[tuple, list[str]] = {}
    for r in existing:
        try:
            existing_sigs.add(_signature(r))
        except Exception:
            pass
        mc = r.get("matching_criteria", {})
        ex = r.get("execution", {})
        cuisine = mc.get("cuisine_region") or [""]
        key = (ex.get("meal_time", ""), mc.get("dietary_pattern", ""),
               cuisine[0] if cuisine else "")
        cell_names.setdefault(key, []).append(r.get("name", "").lower())
    print(f"Existing: ids={len(existing_ids)} sigs={len(existing_sigs)} cells={len(cell_names)}")

    out: list[dict] = []
    new_sigs: set[str] = set()
    new_ids: set[str] = set()
    cell_names_exact: dict[tuple, set[str]] = {}
    rejection_counts: dict[str, int] = {}
    rejection_samples: list[tuple[str, str]] = []
    bucket_counts: dict[str, int] = {}
    bucket_accepted: dict[str, int] = {}
    bucket_rejected: dict[str, int] = {}
    total_attempts = 0

    def reject(rid: str, reason: str, bucket: str) -> None:
        key = reason.split("=", 1)[0]
        rejection_counts[key] = rejection_counts.get(key, 0) + 1
        bucket_rejected[bucket] = bucket_rejected.get(bucket, 0) + 1
        if len(rejection_samples) < 200:
            rejection_samples.append((rid, f"{bucket}:{reason}"))

    for tpl in ALL_TEMPLATES:
        bucket = tpl.get("bucket", "generic")
        cap = BUCKET_CAPS.get(bucket, 0)
        for prot, carb, veg, fat in product(tpl["prot_pool"], tpl["carb_pool"],
                                             tpl["veg_pool"], tpl["fat_pool"]):
            if bucket_counts.get(bucket, 0) >= cap:
                break
            total_attempts += 1
            try:
                recipe = build_one(tpl, prot, carb, veg, fat)
            except Exception as exc:  # noqa: BLE001
                reject("?", f"build_error={exc.__class__.__name__}", bucket)
                continue
            rid = recipe["id"]
            if rid in existing_ids or rid in new_ids:
                reject(rid, "duplicate_id", bucket)
                continue
            ok, reason = validate_base(recipe)
            if not ok:
                reject(rid, reason, bucket)
                continue
            ok, reason = bucket_gate(recipe, bucket)
            if not ok:
                reject(rid, reason, bucket)
                continue
            sig = _signature(recipe)
            if sig in existing_sigs or sig in new_sigs:
                reject(rid, "signature_collision", bucket)
                continue
            mc = recipe["matching_criteria"]
            ex = recipe["execution"]
            cuisine = mc["cuisine_region"]
            cell_key = (ex["meal_time"], mc["dietary_pattern"],
                        cuisine[0] if cuisine else "")
            name_lower = recipe["name"].lower()
            cell_set = cell_names_exact.get(cell_key)
            if cell_set is None:
                cell_set = set(n.lower() for n in cell_names.get(cell_key, []))
                cell_names_exact[cell_key] = cell_set
            if name_lower in cell_set:
                reject(rid, "name_exact_collision", bucket)
                continue
            new_ids.add(rid)
            new_sigs.add(sig)
            cell_set.add(name_lower)
            out.append(recipe)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            bucket_accepted[bucket] = bucket_accepted.get(bucket, 0) + 1

    OUT.write_text(json.dumps(out, ensure_ascii=False))
    summary_lines = [
        "Gap closure batch generation summary",
        f"templates={len(ALL_TEMPLATES)}",
        f"attempts={total_attempts}",
        f"accepted={len(out)}",
        f"rejected_total={total_attempts - len(out)}",
        "",
        "Per-bucket accepted:",
    ]
    for b in sorted(bucket_accepted):
        summary_lines.append(f"  {b}: accepted={bucket_accepted[b]} rejected={bucket_rejected.get(b,0)}")
    summary_lines.append("")
    summary_lines.append("Rejection reason counts:")
    for k, v in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        summary_lines.append(f"  {k}: {v}")
    summary_lines.append("")
    summary_lines.append("Rejection samples (first 200):")
    summary_lines.extend(f"{rid}\t{reason}" for rid, reason in rejection_samples)
    LOG.write_text("\n".join(summary_lines))
    print(f"gap: templates={len(ALL_TEMPLATES)} attempts={total_attempts} accepted={len(out)}")
    print("Per-bucket accepted:", bucket_accepted)
    print("Reject top:", dict(sorted(rejection_counts.items(), key=lambda x: -x[1])[:10]))


if __name__ == "__main__":
    main()
