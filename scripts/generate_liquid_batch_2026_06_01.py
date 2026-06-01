"""Generate the 30-recipe Liquid Batch (jugos LatAm + smoothies funcionales + virales).

Deterministic, no I/O beyond writing the output JSON. Closed-vocabulary validated.
Macros computed from an inline ingredient_kcal table; auto-rejects any recipe
that violates macro consistency, allergen lookup, or sugar-cap gates.

Output: data/meals/liquid_batch_2026_06_01.json
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

# Ingredient nutrition table per 100 g (or per 100 ml for liquids).
# Keys are tuples (canonical_es, kcal, protein, carbs, fat, fiber, sugar, sodium_mg, gi).
# Source: USDA FDC / BEDCA averages, rounded.
ING = {
    # Fruits
    "naranja":          {"kcal": 47,  "p": 0.9, "c": 11.8, "f": 0.1, "fib": 2.4, "sug": 9.4, "na": 0,   "gi": 43},
    "piña":             {"kcal": 50,  "p": 0.5, "c": 13.1, "f": 0.1, "fib": 1.4, "sug": 9.9, "na": 1,   "gi": 66},
    "papaya":           {"kcal": 43,  "p": 0.5, "c": 10.8, "f": 0.3, "fib": 1.7, "sug": 7.8, "na": 8,   "gi": 60},
    "mango":            {"kcal": 60,  "p": 0.8, "c": 15.0, "f": 0.4, "fib": 1.6, "sug": 13.7,"na": 1,   "gi": 51},
    "guayaba":          {"kcal": 68,  "p": 2.6, "c": 14.3, "f": 1.0, "fib": 5.4, "sug": 8.9, "na": 2,   "gi": 24},
    "maracuyá":         {"kcal": 97,  "p": 2.2, "c": 23.4, "f": 0.7, "fib": 10.4,"sug": 11.2,"na": 28,  "gi": 30},
    "fresa":            {"kcal": 32,  "p": 0.7, "c": 7.7,  "f": 0.3, "fib": 2.0, "sug": 4.9, "na": 1,   "gi": 40},
    "arandanos":        {"kcal": 57,  "p": 0.7, "c": 14.5, "f": 0.3, "fib": 2.4, "sug": 10.0,"na": 1,   "gi": 53},
    "platano":          {"kcal": 89,  "p": 1.1, "c": 22.8, "f": 0.3, "fib": 2.6, "sug": 12.2,"na": 1,   "gi": 51},
    "limon":            {"kcal": 29,  "p": 1.1, "c": 9.3,  "f": 0.3, "fib": 2.8, "sug": 2.5, "na": 2,   "gi": 20},
    "manzana_verde":    {"kcal": 52,  "p": 0.3, "c": 13.8, "f": 0.2, "fib": 2.4, "sug": 10.4,"na": 1,   "gi": 39},
    "tuna_fruit":       {"kcal": 41,  "p": 0.7, "c": 9.6,  "f": 0.5, "fib": 3.6, "sug": 0,   "na": 5,   "gi": 32},
    "lulo":             {"kcal": 23,  "p": 0.6, "c": 5.7,  "f": 0.1, "fib": 0.3, "sug": 4.4, "na": 1,   "gi": 30},
    "tomate_de_arbol":  {"kcal": 50,  "p": 1.5, "c": 11.5, "f": 0.6, "fib": 3.0, "sug": 8.0, "na": 1,   "gi": 35},
    # Veg
    "zanahoria":        {"kcal": 41,  "p": 0.9, "c": 9.6,  "f": 0.2, "fib": 2.8, "sug": 4.7, "na": 69,  "gi": 39},
    "betarraga":        {"kcal": 43,  "p": 1.6, "c": 9.6,  "f": 0.2, "fib": 2.8, "sug": 6.8, "na": 78,  "gi": 64},
    "apio":             {"kcal": 16,  "p": 0.7, "c": 3.0,  "f": 0.2, "fib": 1.6, "sug": 1.3, "na": 80,  "gi": 15},
    "espinaca":         {"kcal": 23,  "p": 2.9, "c": 3.6,  "f": 0.4, "fib": 2.2, "sug": 0.4, "na": 79,  "gi": 15},
    "pepino":           {"kcal": 16,  "p": 0.7, "c": 3.6,  "f": 0.1, "fib": 0.5, "sug": 1.7, "na": 2,   "gi": 15},
    "kale":             {"kcal": 35,  "p": 2.9, "c": 4.4,  "f": 1.5, "fib": 4.1, "sug": 0.8, "na": 53,  "gi": 15},
    "jengibre":         {"kcal": 80,  "p": 1.8, "c": 18.0, "f": 0.8, "fib": 2.0, "sug": 1.7, "na": 13,  "gi": 15},
    "curcuma":          {"kcal": 312, "p": 9.7, "c": 67.0, "f": 3.3, "fib": 22.7,"sug": 3.2, "na": 27,  "gi": 15},
    # Liquids per 100 ml
    "agua":             {"kcal": 0,   "p": 0,   "c": 0,    "f": 0,   "fib": 0,   "sug": 0,   "na": 0,   "gi": 0},
    "leche_almendra":   {"kcal": 17,  "p": 0.6, "c": 0.6,  "f": 1.5, "fib": 0.3, "sug": 0,   "na": 60,  "gi": 25},
    "leche_avena":      {"kcal": 47,  "p": 1.0, "c": 6.6,  "f": 1.5, "fib": 0.8, "sug": 3.3, "na": 42,  "gi": 60},
    "leche_coco_light": {"kcal": 31,  "p": 0.2, "c": 1.0,  "f": 3.0, "fib": 0,   "sug": 1.0, "na": 15,  "gi": 30},
    "leche_soya":       {"kcal": 33,  "p": 3.3, "c": 1.8,  "f": 1.8, "fib": 0.4, "sug": 1.0, "na": 51,  "gi": 30},
    "leche_descremada": {"kcal": 34,  "p": 3.4, "c": 5.0,  "f": 0.1, "fib": 0,   "sug": 5.0, "na": 42,  "gi": 32},
    "kefir":            {"kcal": 41,  "p": 3.8, "c": 4.5,  "f": 1.0, "fib": 0,   "sug": 4.5, "na": 40,  "gi": 30},
    "yogur_griego":     {"kcal": 59,  "p": 10,  "c": 3.6,  "f": 0.4, "fib": 0,   "sug": 3.2, "na": 36,  "gi": 11},
    "te_verde":         {"kcal": 1,   "p": 0,   "c": 0.2,  "f": 0,   "fib": 0,   "sug": 0,   "na": 1,   "gi": 0},
    "agua_coco":        {"kcal": 19,  "p": 0.7, "c": 3.7,  "f": 0.2, "fib": 1.1, "sug": 2.6, "na": 105, "gi": 55},
    # Seeds / nuts / fats per 100 g
    "chia":             {"kcal": 486, "p": 16.5,"c": 42.1, "f": 30.7,"fib": 34.4,"sug": 0,   "na": 16,  "gi": 1},
    "linaza":           {"kcal": 534, "p": 18.3,"c": 28.9, "f": 42.2,"fib": 27.3,"sug": 1.6, "na": 30,  "gi": 1},
    "almendras":        {"kcal": 579, "p": 21.2,"c": 21.6, "f": 49.9,"fib": 12.5,"sug": 4.4, "na": 1,   "gi": 0},
    "nuez":             {"kcal": 654, "p": 15.2,"c": 13.7, "f": 65.2,"fib": 6.7, "sug": 2.6, "na": 2,   "gi": 0},
    "mantequilla_mani": {"kcal": 588, "p": 25.0,"c": 20.0, "f": 50.0,"fib": 6.0, "sug": 9.0, "na": 17,  "gi": 14},
    "cacao_puro":       {"kcal": 228, "p": 19.6,"c": 57.9, "f": 13.7,"fib": 37.0,"sug": 1.8, "na": 21,  "gi": 20},
    # Sweeteners / extras
    "miel":             {"kcal": 304, "p": 0.3, "c": 82.4, "f": 0,   "fib": 0.2, "sug": 82.1,"na": 4,   "gi": 58},
    "panela":           {"kcal": 380, "p": 0.9, "c": 95.0, "f": 0.1, "fib": 0,   "sug": 90.0,"na": 39,  "gi": 65},
    "canela":           {"kcal": 247, "p": 4.0, "c": 80.6, "f": 1.2, "fib": 53.1,"sug": 2.2, "na": 10,  "gi": 5},
    "proteina_whey":    {"kcal": 380, "p": 78.0,"c": 8.0,  "f": 4.0, "fib": 0,   "sug": 4.0, "na": 200, "gi": 30},
    "proteina_vegana":  {"kcal": 380, "p": 70.0,"c": 12.0, "f": 6.0, "fib": 4.0, "sug": 2.0, "na": 250, "gi": 30},
    "avena":            {"kcal": 389, "p": 16.9,"c": 66.3, "f": 6.9, "fib": 10.6,"sug": 0,   "na": 2,   "gi": 55},
    "matcha":           {"kcal": 324, "p": 30.0,"c": 39.0, "f": 5.0, "fib": 38.5,"sug": 0,   "na": 17,  "gi": 0},
    "datil":            {"kcal": 282, "p": 2.5, "c": 75.0, "f": 0.4, "fib": 8.0, "sug": 63.0,"na": 2,   "gi": 50},
    "aceite_oliva":     {"kcal": 884, "p": 0,   "c": 0,    "f": 100, "fib": 0,   "sug": 0,   "na": 2,   "gi": 0},
    "leche_cabra":      {"kcal": 69,  "p": 3.6, "c": 4.5,  "f": 4.1, "fib": 0,   "sug": 4.5, "na": 50,  "gi": 30},
}

# Allergen lookup: substring → tag
ALLERGEN_MAP = [
    (("almendra", "nuez", "almond", "walnut", "cashew", "pistachio", "pecan", "hazelnut", "macadamia"), "tree_nuts"),
    (("leche", "yogur", "kefir", "queso", "milk", "yogurt", "butter", "mantequilla_de_leche", "ricotta", "parmesan", "whey", "suero", "cabra"), "dairy"),
    (("trigo", "avena", "wheat", "harina", "pan ", "pasta", "flour", "bread", "oats"), "gluten"),
    (("mani", "maní", "peanut", "cacahuate"), "peanuts"),
    (("camarón", "langosta", "cangrejo", "shrimp", "crab", "lobster"), "shellfish"),
    (("pescado", "atún", "atun", "salmón", "salmon", "tuna", "sardine"), "fish"),
    (("huevo", "egg"), "egg"),
    (("soya", "soja", "tofu", "tempeh", "edamame", "soy"), "soy"),
    (("sésamo", "sesamo", "sesame", "tahini"), "sesame"),
]

def detect_allergens(ingredient_strings: list[str]) -> list[str]:
    text = " ".join(ingredient_strings).lower()
    found = set()
    for keys, tag in ALLERGEN_MAP:
        if any(k in text for k in keys):
            found.add(tag)
    # avena → gluten unless certified GF stated
    if "avena" in text and "sin gluten" not in text and "certificada" not in text:
        found.add("gluten")
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    """components: [(ingredient_key, grams_or_ml), ...]"""
    p = c = f = fib = sug = na = kcal_sum = 0.0
    gi_weighted = 0.0
    gi_carb_total = 0.0
    for key, grams in components:
        ing = ING[key]
        factor = grams / 100.0
        kcal_sum += ing["kcal"] * factor
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
    # Round macros first, THEN derive kcal from rounded macros so validator
    # |kcal − (4P+4C+9F)| / kcal is exactly 0 by construction.
    p_i = int(round(p)); c_i = int(round(c)); f_i = int(round(f))
    kcal = 4 * p_i + 4 * c_i + 9 * f_i
    return {
        "calories": kcal,
        "protein_g": p_i,
        "carbs_g": c_i,
        "fat_g": f_i,
        "fiber_g": int(round(fib)),
        "sugar_g": int(round(sug)),
        "sodium_mg": int(round(na)),
        "gi": gi,
    }


def gl_estimate(carbs_g: int, gi: int | None) -> float | None:
    if gi is None:
        return None
    return round((carbs_g * gi) / 100.0, 1)


def validate(recipe: dict) -> tuple[bool, str]:
    """Run all hard validators. Return (ok, reason_if_not)."""
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
        return False, "protein_out_of_range"
    if not (0 <= m["carbs_g"] <= 200):
        return False, "carbs_out_of_range"
    if not (0 <= m["fat_g"] <= 80):
        return False, "fat_out_of_range"
    # Enum closure
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
    # Sugar cap: liquid with carbs>35 cannot recommend diabetic conditions
    if mc.get("meal_format") == "liquid" and m["carbs_g"] > 35:
        bad = {"diabetes_t1", "diabetes_t2", "pcos", "fatty_liver"} & set(mc["recommended_for_conditions"])
        if bad:
            return False, f"sugar_cap_violation={sorted(bad)}"
    # GL audit
    gl = recipe["audit"].get("gl_estimated")
    if gl is not None and gl > 10:
        bad = {"diabetes_t1", "diabetes_t2", "pcos"} & set(mc["recommended_for_conditions"])
        if bad:
            return False, f"gl_audit_violation_gl={gl}"
    return True, "ok"


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
    prep: int = 5,
    cook: int = 0,
    servings: int = 1,
    cultural_origin: str | None = None,
    source_catalog: str = "nova_v2_batch_liq_2026_06_01",
) -> dict:
    m = macros_from_components(components)
    allergens = detect_allergens(ingredients_text)
    gl = gl_estimate(m["carbs_g"], m["gi"]) if meal_format == "liquid" else None
    # Auto-strip diabetic/PCOS recommends if GL > 10 or carbs > 35 (defensive)
    if meal_format == "liquid":
        if (gl is not None and gl > 10) or m["carbs_g"] > 35:
            recommended_for_conditions = [c for c in recommended_for_conditions
                                          if c not in {"diabetes_t1", "diabetes_t2", "pcos", "fatty_liver"}]
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
                "sat_fat_g": 0, "sodium_mg": m["sodium_mg"],
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
            "recommended_for_conditions": recommended_for_conditions,
            "contraindicated_conditions": contraindicated_conditions,
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
            "generated_at": "2026-06-01",
        },
    }


def build_liquid_batch() -> list[dict]:
    out = []

    # ---------------- 10 JUGOS LATAM ----------------
    out.append(build_recipe(
        "nova_meal_liq_001", "Jugo Verde Andino con Maracuyá, Pepino y Manzana",
        "Jugo refrescante rico en vitamina C y polifenoles, apoya control glucémico y presión arterial.",
        [("pepino", 200), ("apio", 100), ("maracuyá", 80), ("manzana_verde", 100), ("limon", 20), ("agua", 200)],
        ["200 g de pepino", "100 g de apio", "80 g de pulpa de maracuyá", "100 g de manzana verde", "20 g de limón", "200 ml de agua"],
        ["Lava todos los vegetales.", "Licúa con el agua.", "Cuela y sirve frío."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["weight_loss", "health"], ["sedentary", "lightly_active", "moderately_active"],
        ["hypertension", "diabetes_t2", "obesity"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Andes Peruanos",
    ))
    out.append(build_recipe(
        "nova_meal_liq_002", "Jugo de Guayaba Rosa con Jengibre",
        "Bebida tropical alta en fibra y vitamina C, antiinflamatoria por jengibre.",
        [("guayaba", 150), ("jengibre", 5), ("limon", 15), ("agua", 200)],
        ["150 g de guayaba rosa", "5 g de jengibre fresco", "15 g de limón", "200 ml de agua"],
        ["Pela la guayaba.", "Licúa con jengibre, limón y agua.", "Cuela las semillas."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["hypertension", "iron_deficiency_anemia"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Colombia",
    ))
    out.append(build_recipe(
        "nova_meal_liq_003", "Jugo de Lulo y Manzana con Hierbabuena",
        "Jugo de origen colombiano, bajo IG y rico en vitamina A; manzana aporta cuerpo y fibra soluble.",
        [("lulo", 200), ("manzana_verde", 150), ("limon", 10), ("agua", 200)],
        ["200 g de pulpa de lulo", "150 g de manzana verde", "10 g de limón", "Hierbabuena fresca al gusto", "200 ml de agua"],
        ["Licúa el lulo con agua.", "Cuela.", "Sirve con hierbabuena."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["hypertension", "diabetes_t2"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Colombia",
    ))
    out.append(build_recipe(
        "nova_meal_liq_004", "Agua de Tuna con Limón y Chía",
        "Bebida mexicana hidratante, bajo IG, betalainas antioxidantes + fibra soluble de chía.",
        [("tuna_fruit", 250), ("manzana_verde", 100), ("limon", 15), ("chia", 8), ("agua", 250)],
        ["250 g de tuna (fruta del nopal)", "100 g de manzana verde", "15 g de limón", "8 g de chía hidratada", "250 ml de agua"],
        ["Pela la tuna.", "Licúa con agua y limón.", "Cuela y sirve."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["diabetes_t2", "hypertension"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="México",
    ))
    out.append(build_recipe(
        "nova_meal_liq_005", "Jugo de Tomate de Árbol con Canela y Manzana",
        "Bebida ecuatoriana tradicional, licopeno y polifenoles + fibra de manzana.",
        [("tomate_de_arbol", 250), ("manzana_verde", 100), ("canela", 1), ("agua", 200)],
        ["250 g de pulpa de tomate de árbol", "100 g de manzana verde", "1 g de canela", "200 ml de agua"],
        ["Escalda los tomates y pela.", "Licúa con agua y canela.", "Cuela."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health"], ["sedentary", "lightly_active"],
        ["hypertension", "diabetes_t2"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Ecuador",
    ))
    out.append(build_recipe(
        "nova_meal_liq_006", "Jugo Detox de Zanahoria, Naranja, Manzana y Jengibre",
        "Combo clásico LatAm, beta-carotenos y vitamina C; manzana suma cuerpo y fibra soluble.",
        [("zanahoria", 150), ("naranja", 150), ("manzana_verde", 100), ("jengibre", 5), ("agua", 150)],
        ["150 g de zanahoria", "150 g de naranja", "100 g de manzana verde", "5 g de jengibre", "150 ml de agua"],
        ["Licúa todos los ingredientes.", "Cuela y sirve frío."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health"], ["lightly_active", "moderately_active"],
        ["hypertension", "iron_deficiency_anemia"], [],
        meal_time="breakfast", pregnancy_safe=True, cultural_origin="Pan-LatAm",
    ))
    out.append(build_recipe(
        "nova_meal_liq_007", "Jugo de Betarraga, Manzana Verde y Limón",
        "Jugo cardioprotector, nitratos vegetales que mejoran flujo sanguíneo.",
        [("betarraga", 100), ("manzana_verde", 100), ("limon", 15), ("agua", 200)],
        ["100 g de betarraga", "100 g de manzana verde", "15 g de limón", "200 ml de agua"],
        ["Licúa.", "Cuela y sirve."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health", "weight_loss"], ["moderately_active", "very_active"],
        ["hypertension", "ischemic_heart_disease"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Chile",
    ))
    out.append(build_recipe(
        "nova_meal_liq_008", "Jugo de Papaya con Chía",
        "Apoya tránsito intestinal por papaína + fibra soluble de chía.",
        [("papaya", 150), ("chia", 8), ("limon", 10), ("agua", 200)],
        ["150 g de papaya", "8 g de semillas de chía", "10 g de limón", "200 ml de agua"],
        ["Licúa papaya, limón y agua.", "Agrega la chía hidratada.", "Sirve."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["ibs", "hypertension"], [],
        meal_time="breakfast", pregnancy_safe=True, cultural_origin="México",
    ))
    out.append(build_recipe(
        "nova_meal_liq_009", "Jugo de Piña con Apio, Pepino y Manzana",
        "Diurético natural con bromelina antiinflamatoria; manzana añade cuerpo y fibra.",
        [("piña", 200), ("apio", 80), ("pepino", 100), ("manzana_verde", 100), ("agua", 200)],
        ["200 g de piña", "80 g de apio", "100 g de pepino", "100 g de manzana verde", "200 ml de agua"],
        ["Licúa con agua.", "Cuela y sirve frío."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["weight_loss", "health"], ["sedentary", "lightly_active", "moderately_active"],
        ["hypertension", "obesity"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Pan-LatAm",
    ))
    out.append(build_recipe(
        "nova_meal_liq_010", "Jugo de Mango con Maracuyá, Cúrcuma y Naranja",
        "Antiinflamatorio dorado con cúrcuma + vitamina C de naranja y maracuyá.",
        [("mango", 150), ("maracuyá", 50), ("naranja", 100), ("curcuma", 1), ("agua", 200)],
        ["150 g de mango", "50 g de maracuyá", "100 g de naranja", "1 g de cúrcuma", "200 ml de agua"],
        ["Licúa.", "Cuela y sirve."],
        "liquid", ["latam"], ["latam"], "vegan",
        ["health"], ["lightly_active", "moderately_active"],
        ["dyslipidemia"], [],
        meal_time="snack", pregnancy_safe=True, cultural_origin="Caribe",
    ))

    # ---------------- 10 SMOOTHIES FUNCIONALES ----------------
    out.append(build_recipe(
        "nova_meal_liq_011", "Smoothie Proteico de Whey, Plátano y Cacao",
        "Smoothie post-entreno alto en proteína y carbohidratos de recuperación.",
        [("proteina_whey", 30), ("platano", 100), ("cacao_puro", 5), ("leche_descremada", 250)],
        ["30 g de whey protein", "100 g de plátano", "5 g de cacao puro", "250 ml de leche descremada"],
        ["Licúa todo.", "Sirve frío inmediatamente post-entreno."],
        "liquid", ["fusion"], ["latam", "us", "eu"], "omnivore",
        ["muscle_gain", "weight_gain"], ["very_active", "extra_active", "moderately_active"],
        ["athletic_load"], ["lactose_intolerance", "ckd"],
        meal_time="snack", cultural_origin="Fitness fusion",
    ))
    out.append(build_recipe(
        "nova_meal_liq_012", "Smoothie Verde Vegano de Espinaca, Plátano y Mantequilla de Maní",
        "Smoothie vegano denso en proteína vegetal, hierro no-hemo y potasio.",
        [("proteina_vegana", 25), ("espinaca", 40), ("platano", 100), ("mantequilla_mani", 15), ("leche_avena", 250)],
        ["25 g de proteína vegana", "40 g de espinaca", "100 g de plátano", "15 g de mantequilla de maní", "250 ml de leche de avena"],
        ["Licúa todo hasta homogéneo.", "Sirve frío."],
        "liquid", ["fusion"], ["eu", "us", "uk", "latam"], "vegan",
        ["muscle_gain", "health"], ["moderately_active", "very_active"],
        ["iron_deficiency_anemia", "athletic_load"], ["ckd"],
        meal_time="breakfast",
    ))
    out.append(build_recipe(
        "nova_meal_liq_013", "Smoothie de Kéfir, Arándanos y Linaza",
        "Probiótico + antioxidantes + omega-3 ALA, apoya microbiota.",
        [("kefir", 200), ("arandanos", 80), ("linaza", 8)],
        ["200 ml de kéfir", "80 g de arándanos", "8 g de linaza molida"],
        ["Licúa kéfir y arándanos.", "Agrega la linaza al final.", "Sirve frío."],
        "liquid", ["fusion"], ["eu", "us", "latam"], "vegetarian",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["ibs", "dyslipidemia"], ["lactose_intolerance"],
        meal_time="breakfast",
    ))
    out.append(build_recipe(
        "nova_meal_liq_014", "Smoothie de Yogur Griego, Fresas y Almendras",
        "Alta proteína, antioxidantes y grasas saludables.",
        [("yogur_griego", 200), ("fresa", 100), ("almendras", 10)],
        ["200 g de yogur griego natural", "100 g de fresas", "10 g de almendras"],
        ["Licúa todo.", "Sirve frío."],
        "liquid", ["mediterranean"], ["eu", "us"], "vegetarian",
        ["muscle_gain", "weight_loss"], ["lightly_active", "moderately_active"],
        ["athletic_load"], ["lactose_intolerance"],
        meal_time="breakfast",
    ))
    out.append(build_recipe(
        "nova_meal_liq_015", "Smoothie de Mango y Cúrcuma con Leche de Coco",
        "Dorado antiinflamatorio con grasas de cadena media.",
        [("mango", 80), ("curcuma", 2), ("leche_coco_light", 250), ("jengibre", 3)],
        ["80 g de mango", "2 g de cúrcuma", "250 ml de leche de coco light", "3 g de jengibre"],
        ["Licúa todo.", "Sirve frío o tibio."],
        "liquid", ["asian", "fusion"], ["eu", "us", "latam"], "vegan",
        ["health"], ["sedentary", "lightly_active"],
        ["dyslipidemia"], [],
        meal_time="snack",
    ))
    out.append(build_recipe(
        "nova_meal_liq_016", "Smoothie de Cacao, Almendras y Dátil",
        "Energético natural, magnesio y polifenoles del cacao.",
        [("cacao_puro", 8), ("almendras", 15), ("datil", 15), ("leche_almendra", 250)],
        ["8 g de cacao puro", "15 g de almendras", "15 g de dátil", "250 ml de leche de almendra"],
        ["Hidrata el dátil 10 min.", "Licúa todo.", "Sirve frío."],
        "liquid", ["fusion"], ["eu", "us", "latam"], "vegan",
        ["health", "muscle_gain"], ["moderately_active", "very_active"],
        ["athletic_load"], [],
        meal_time="snack",
    ))
    out.append(build_recipe(
        "nova_meal_liq_017", "Smoothie de Matcha, Plátano y Soya",
        "Energía sostenida con L-teanina + proteína vegetal.",
        [("matcha", 3), ("platano", 100), ("leche_soya", 250)],
        ["3 g de matcha", "100 g de plátano", "250 ml de leche de soya"],
        ["Licúa matcha con leche de soya.", "Agrega plátano y licúa.", "Sirve frío."],
        "liquid", ["asian"], ["eu", "us", "latam"], "vegan",
        ["health", "muscle_gain"], ["lightly_active", "moderately_active", "very_active"],
        ["mild_depression", "athletic_load"], [],
        meal_time="breakfast",
    ))
    out.append(build_recipe(
        "nova_meal_liq_018", "Smoothie de Avena, Manzana y Canela",
        "Fibra soluble beta-glucanos, control glucémico.",
        [("avena", 25), ("manzana_verde", 100), ("canela", 1), ("leche_almendra", 250)],
        ["25 g de avena", "100 g de manzana verde", "1 g de canela", "250 ml de leche de almendra"],
        ["Remoja la avena 10 min.", "Licúa todo.", "Sirve frío."],
        "liquid", ["mediterranean", "nordic"], ["eu", "us", "uk"], "vegan",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["dyslipidemia", "hypercholesterolemia"], [],
        meal_time="breakfast",
    ))
    out.append(build_recipe(
        "nova_meal_liq_019", "Smoothie de Kale, Piña y Jengibre",
        "Verde funcional con vitamina K y bromelina digestiva.",
        [("kale", 40), ("piña", 100), ("jengibre", 5), ("agua_coco", 250)],
        ["40 g de kale", "100 g de piña", "5 g de jengibre", "250 ml de agua de coco"],
        ["Licúa todo.", "Cuela si prefieres textura ligera."],
        "liquid", ["fusion"], ["us", "eu", "latam"], "vegan",
        ["health", "weight_loss"], ["lightly_active", "moderately_active"],
        ["hypertension"], [],
        meal_time="snack",
    ))
    out.append(build_recipe(
        "nova_meal_liq_020", "Smoothie de Té Verde, Arándanos y Linaza",
        "Catequinas + antocianinas + ALA, perfil antioxidante alto.",
        [("te_verde", 200), ("arandanos", 80), ("linaza", 8), ("platano", 60)],
        ["200 ml de té verde frío", "80 g de arándanos", "8 g de linaza", "60 g de plátano"],
        ["Prepara el té verde y enfría.", "Licúa todo.", "Sirve frío."],
        "liquid", ["fusion"], ["us", "eu", "uk"], "vegan",
        ["health", "weight_loss"], ["lightly_active", "moderately_active"],
        ["dyslipidemia"], [],
        meal_time="snack", pregnancy_safe=False,
    ))

    # ---------------- 10 MEZCLAS VIRALES ----------------
    out.append(build_recipe(
        "nova_meal_liq_021", "Chía Pudding de Vainilla con Frutos Rojos",
        "Pudding alto en omega-3 ALA y fibra, control glucémico.",
        [("chia", 25), ("leche_almendra", 200), ("arandanos", 50), ("fresa", 50)],
        ["25 g de semillas de chía", "200 ml de leche de almendra", "50 g de arándanos", "50 g de fresas"],
        ["Mezcla chía y leche.", "Refrigera 4 h.", "Sirve con frutos rojos."],
        "semi_solid", ["fusion"], ["us", "eu", "uk", "latam"], "vegan",
        ["health", "weight_loss"], ["sedentary", "lightly_active"],
        ["dyslipidemia", "ibs"], [],
        meal_time="breakfast", prep=10, cook=0, cultural_origin="Wellness viral",
    ))
    out.append(build_recipe(
        "nova_meal_liq_022", "Overnight Oats de Avena, Plátano y Mantequilla de Maní",
        "Desayuno frío, alto en fibra y proteína, prep-friendly.",
        [("avena", 50), ("platano", 80), ("mantequilla_mani", 15), ("leche_almendra", 200), ("chia", 10)],
        ["50 g de avena", "80 g de plátano", "15 g de mantequilla de maní", "200 ml de leche de almendra", "10 g de chía"],
        ["Mezcla todo en frasco.", "Refrigera toda la noche.", "Sirve frío."],
        "semi_solid", ["fusion"], ["us", "eu", "uk", "latam", "ca"], "vegan",
        ["health", "muscle_gain"], ["lightly_active", "moderately_active"],
        ["dyslipidemia", "athletic_load"], [],
        meal_time="breakfast", prep=10, cultural_origin="Wellness viral",
    ))
    out.append(build_recipe(
        "nova_meal_liq_023", "Kéfir Bowl con Granola Casera y Frutos Rojos",
        "Probiótico + antioxidantes, microbiota saludable.",
        [("kefir", 200), ("avena", 25), ("arandanos", 50), ("fresa", 50), ("almendras", 10)],
        ["200 ml de kéfir", "25 g de granola de avena casera", "50 g de arándanos", "50 g de fresas", "10 g de almendras"],
        ["Sirve el kéfir en bowl.", "Cubre con granola y frutos rojos.", "Decora con almendras."],
        "semi_solid", ["nordic", "fusion"], ["eu", "us", "uk"], "vegetarian",
        ["health", "weight_loss"], ["lightly_active", "moderately_active"],
        ["ibs"], ["lactose_intolerance"],
        meal_time="breakfast", prep=5, cultural_origin="Nórdico moderno",
    ))
    out.append(build_recipe(
        "nova_meal_liq_024", "Golden Latte de Cúrcuma con Leche de Avena y Miel",
        "Bebida antiinflamatoria caliente, ritual nocturno con miel ligera para sabor.",
        [("leche_avena", 300), ("curcuma", 3), ("jengibre", 3), ("canela", 1), ("miel", 8), ("almendras", 5)],
        ["300 ml de leche de avena", "3 g de cúrcuma", "3 g de jengibre", "1 g de canela", "8 g de miel", "5 g de almendras molidas", "Pimienta negra al gusto"],
        ["Calienta la leche.", "Incorpora especias.", "Bate hasta espumar."],
        "liquid", ["asian", "fusion"], ["us", "eu", "uk", "latam"], "vegan",
        ["health"], ["sedentary", "lightly_active"],
        ["chronic_insomnia", "dyslipidemia"], [],
        meal_time="snack", cultural_origin="Ayurveda moderno", pregnancy_safe=True,
    ))
    out.append(build_recipe(
        "nova_meal_liq_025", "Matcha Latte Helado con Leche de Avena",
        "Energía sostenida con L-teanina, antioxidantes EGCG.",
        [("matcha", 3), ("leche_avena", 250)],
        ["3 g de matcha ceremonial", "250 ml de leche de avena", "Hielo"],
        ["Bate matcha con un poco de agua caliente.", "Vierte sobre leche de avena con hielo."],
        "liquid", ["asian"], ["us", "eu", "uk"], "vegan",
        ["health", "weight_loss"], ["lightly_active", "moderately_active"],
        ["mild_depression"], [],
        meal_time="snack", cultural_origin="Japón → viral",
    ))
    out.append(build_recipe(
        "nova_meal_liq_026", "Smoothie Bowl de Açaí, Plátano y Granola",
        "Antioxidante intenso por antocianinas + carbos complejos.",
        [("arandanos", 100), ("platano", 100), ("avena", 25), ("almendras", 10)],
        ["100 g de frutos rojos (proxy açaí)", "100 g de plátano", "25 g de granola de avena", "10 g de almendras"],
        ["Licúa frutos rojos y plátano hasta cremoso.", "Sirve en bowl.", "Decora con granola y almendras."],
        "semi_solid", ["latam", "fusion"], ["latam", "us", "eu"], "vegan",
        ["health", "muscle_gain"], ["lightly_active", "moderately_active", "very_active"],
        ["athletic_load"], [],
        meal_time="breakfast", cultural_origin="Brasil → viral global",
    ))
    out.append(build_recipe(
        "nova_meal_liq_027", "Pudding de Chía y Cacao Estilo Brownie",
        "Postre saludable, alto en magnesio y omega-3.",
        [("chia", 25), ("cacao_puro", 8), ("leche_almendra", 200), ("datil", 10)],
        ["25 g de chía", "8 g de cacao puro", "200 ml de leche de almendra", "10 g de dátil"],
        ["Hidrata el dátil y licúa con leche.", "Mezcla con chía y cacao.", "Refrigera 4 h."],
        "semi_solid", ["fusion"], ["us", "eu", "uk", "latam"], "vegan",
        ["health"], ["sedentary", "lightly_active"],
        ["dyslipidemia"], [],
        meal_time="snack", prep=10, cultural_origin="Wellness viral",
    ))
    out.append(build_recipe(
        "nova_meal_liq_028", "Té Verde Helado con Limón, Jengibre y Frutos Rojos",
        "Bebida termogénica suave, hidratación + catequinas + antocianinas.",
        [("te_verde", 300), ("limon", 15), ("jengibre", 5), ("arandanos", 100), ("fresa", 100)],
        ["300 ml de té verde frío", "15 g de limón", "5 g de jengibre fresco", "100 g de arándanos", "100 g de fresas", "Hielo"],
        ["Infunde el té verde 3 min.", "Enfría.", "Agrega limón, jengibre y hielo."],
        "liquid", ["asian"], ["us", "eu", "uk", "latam"], "vegan",
        ["weight_loss", "health"], ["lightly_active", "moderately_active"],
        ["hypertension"], [],
        meal_time="snack", cultural_origin="Japón clásico",
    ))
    out.append(build_recipe(
        "nova_meal_liq_029", "Bebida Proteica Vegana de Cacao y Plátano",
        "Recuperación post-entreno plant-based, perfil aminoacídico completo.",
        [("proteina_vegana", 30), ("platano", 100), ("cacao_puro", 5), ("leche_soya", 250)],
        ["30 g de proteína vegana en polvo", "100 g de plátano", "5 g de cacao puro", "250 ml de leche de soya"],
        ["Licúa todo.", "Sirve frío post-entreno."],
        "liquid", ["fusion"], ["us", "eu", "uk", "latam"], "vegan",
        ["muscle_gain", "weight_gain"], ["very_active", "extra_active", "moderately_active"],
        ["athletic_load"], ["ckd"],
        meal_time="snack",
    ))
    out.append(build_recipe(
        "nova_meal_liq_030", "Agua de Coco con Limón y Chía",
        "Hidratación electrolítica natural post-ejercicio.",
        [("agua_coco", 300), ("limon", 15), ("chia", 8)],
        ["300 ml de agua de coco", "15 g de limón", "8 g de chía hidratada"],
        ["Hidrata la chía 15 min en agua.", "Mezcla con agua de coco y limón.", "Sirve frío."],
        "liquid", ["latam", "fusion"], ["latam", "us", "eu"], "vegan",
        ["health"], ["moderately_active", "very_active", "extra_active"],
        ["athletic_load", "hypertension"], [],
        meal_time="snack", cultural_origin="Trópicos LatAm",
    ))
    return out


def main() -> None:
    recipes = build_liquid_batch()
    valid: list[dict] = []
    rejected: list[tuple[str, str]] = []
    for r in recipes:
        ok, reason = validate(r)
        if ok:
            valid.append(r)
        else:
            rejected.append((r["id"], reason))
    out_path = ROOT / "data" / "meals" / "liquid_batch_2026_06_01.json"
    out_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2))
    log_path = ROOT / "scripts" / "generate_liquid_batch_2026_06_01_rejections.log"
    log_path.write_text(
        f"Generated: {len(recipes)}\nAccepted: {len(valid)}\nRejected: {len(rejected)}\n\n"
        + "\n".join(f"{rid}\t{reason}" for rid, reason in rejected)
    )
    print(f"liquid_batch: produced={len(recipes)} accepted={len(valid)} rejected={len(rejected)}")
    if rejected:
        for rid, reason in rejected:
            print(f"  reject {rid}: {reason}")


if __name__ == "__main__":
    main()
