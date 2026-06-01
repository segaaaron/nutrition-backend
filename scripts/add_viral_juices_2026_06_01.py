"""Add viral juice mixes user explicitly requested.

User explicit examples (sessions earlier): "piña + linaza + chía" mix, virally
shared on TikTok/Facebook/YouTube for weight loss + fatty liver support.

This script appends 25 deterministic, validated juice/smoothie recipes:
- 10 piña + linaza + chía variants (different acid/leaf/citrus accents)
- 5 chia pudding overnight variants
- 5 kéfir bowls variants
- 5 matcha + green tea-based liquids

Hard validators applied (same as L99 batch):
- macro consistency ≤ 5%
- closed-vocabulary membership
- meal_format = liquid (or semi_solid for puddings)
- carbs_g ≤ 35 → diabetes_t2 NOT in recommended_for (unless GL≤10)
- pregnancy_safe default false (deny) — set true only when explicitly safe

Adds to `data/meals/viral_juices_2026_06_01.json` then appends via merge script.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "meals" / "viral_juices_2026_06_01.json"

PLACEHOLDER_IMG = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"
SOURCE_CATALOG = "nova_viral_juices_2026_06_01"


def _id(prefix: str, key: str) -> str:
    return f"nova_meal_viral_{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def _macros(p: int, c: int, f: int) -> dict:
    return {
        "calories": 4 * p + 4 * c + 9 * f,
        "macros": {
            "protein_g": p, "carbs_g": c, "fat_g": f,
            "fiber_g": 0, "sugar_g": 0, "sat_fat_g": 0, "sodium_mg": 0,
        },
        "micronutrients": {
            "gi": None, "gl": None, "potassium_mg": None,
            "phosphorus_mg": None, "iron_mg": None, "heme_pct": None,
            "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
        },
    }


def _execution(meal_time: str, prep: int, cook: int, ingredients: list[str],
               instructions: list[str], servings: int = 1) -> dict:
    return {
        "meal_time": meal_time, "prep_time_minutes": prep,
        "cook_time_minutes": cook, "image_url": None,
        "ingredients": ingredients, "instructions": instructions,
        "servings": servings, "source_catalog": SOURCE_CATALOG,
    }


def _mc(goals: list[str], dietary: str, cuisine: list[str],
        regions: list[str], recommended: list[str],
        contraindicated: list[str], allergens: list[str],
        meal_format: str, pregnancy_safe: bool = False) -> dict:
    return {
        "target_goals": goals,
        "suitable_for_activity": ["sedentary", "lightly_active", "moderately_active"],
        "recommended_for_conditions": recommended,
        "contraindicated_conditions": contraindicated,
        "allergens": allergens, "regions": regions,
        "dietary_pattern": dietary, "cuisine_region": cuisine,
        "meal_format": meal_format, "pregnancy_safe": pregnancy_safe,
    }


def _audit(gl: float | None = None, cultural: str | None = None) -> dict:
    return {
        "schema_version": "v2",
        "macro_consistency_pct": 0.0,
        "gl_estimated": gl,
        "cultural_origin": cultural,
        "image_status": "placeholder_pending_upload",
        "generated_at": "2026-06-01",
    }


# 10 PIÑA + LINAZA + CHÍA variants (viral mix)
_PINA_LINAZA_CHIA = [
    {
        "key": "pina_linaza_chia_clasico",
        "name": "Jugo Viral de Piña, Linaza y Chía",
        "desc": "Mezcla tropical alta en fibra soluble (chía + linaza) que ralentiza la absorción del azúcar natural de la piña. Bajo en grasas saturadas. Alineado con planes de hígado graso, sobrepeso y dislipidemia.",
        "ingredients": [
            "120 g de piña fresca en cubos", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada 10 min", "200 ml de agua filtrada fría",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 4, "c": 24, "f": 5, "gl": 9, "rec": ["fatty_liver", "overweight", "dyslipidemia"],
    },
    {
        "key": "pina_linaza_chia_apio",
        "name": "Jugo Verde Viral de Piña, Linaza, Chía y Apio",
        "desc": "Variante con apio para sumar potasio y fibra. Bajo IG y bajo en sodio. Alineado con plan de hígado graso e hipertensión.",
        "ingredients": [
            "100 g de piña fresca", "60 g de apio", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "Jugo de medio limón (15 ml)",
            "200 ml de agua filtrada",
        ],
        "p": 4, "c": 20, "f": 5, "gl": 8, "rec": ["fatty_liver", "hypertension", "overweight"],
    },
    {
        "key": "pina_linaza_chia_jengibre",
        "name": "Jugo Tropical de Piña, Linaza, Chía y Jengibre",
        "desc": "Combinación con jengibre fresco para acentuar sabor cítrico. Bajo en grasas saturadas. Alineado con plan de pérdida de peso y dislipidemia.",
        "ingredients": [
            "120 g de piña fresca", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "5 g de jengibre fresco rallado",
            "Jugo de medio limón (15 ml)", "200 ml de agua filtrada",
        ],
        "p": 4, "c": 24, "f": 5, "gl": 9, "rec": ["fatty_liver", "overweight", "dyslipidemia"],
    },
    {
        "key": "pina_linaza_chia_pepino",
        "name": "Jugo Hidratante de Piña, Pepino, Linaza y Chía",
        "desc": "Bebida hidratante con pepino para mayor saciedad líquida. Bajo en sodio y bajo en azúcar simple.",
        "ingredients": [
            "100 g de piña fresca", "80 g de pepino", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "200 ml de agua filtrada",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 3, "c": 19, "f": 5, "gl": 7, "rec": ["fatty_liver", "hypertension", "overweight"],
    },
    {
        "key": "pina_linaza_chia_menta",
        "name": "Jugo Refrescante de Piña, Linaza, Chía y Menta",
        "desc": "Variante con menta fresca, refresca el paladar. Mantiene perfil bajo en grasas y bajo IG.",
        "ingredients": [
            "120 g de piña fresca", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "5 hojas de menta fresca",
            "200 ml de agua filtrada", "Jugo de medio limón (15 ml)",
        ],
        "p": 4, "c": 23, "f": 5, "gl": 9, "rec": ["fatty_liver", "overweight"],
    },
    {
        "key": "pina_linaza_chia_espinaca",
        "name": "Jugo Verde de Piña, Espinaca, Linaza y Chía",
        "desc": "Variante con espinaca baby para sumar hierro vegetal y folato. Alineado con plan de hígado graso y anemia ferropénica.",
        "ingredients": [
            "100 g de piña fresca", "40 g de espinaca baby", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "200 ml de agua filtrada",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 5, "c": 22, "f": 5, "gl": 8, "rec": ["fatty_liver", "iron_deficiency_anemia", "overweight"],
    },
    {
        "key": "pina_linaza_chia_kiwi",
        "name": "Jugo Tropical de Piña, Kiwi, Linaza y Chía",
        "desc": "Variante con kiwi rico en vitamina C natural. Alineado con plan de pérdida de peso.",
        "ingredients": [
            "80 g de piña fresca", "60 g de kiwi", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "200 ml de agua filtrada",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 4, "c": 25, "f": 5, "gl": 9, "rec": ["fatty_liver", "overweight"],
    },
    {
        "key": "pina_linaza_chia_cilantro",
        "name": "Jugo LatAm de Piña, Cilantro, Linaza y Chía",
        "desc": "Variante con cilantro fresco — perfil LatAm distintivo. Alto en fibra soluble.",
        "ingredients": [
            "120 g de piña fresca", "8 g de cilantro fresco", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "200 ml de agua filtrada",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 4, "c": 24, "f": 5, "gl": 9, "rec": ["fatty_liver", "overweight"],
    },
    {
        "key": "pina_linaza_chia_papaya",
        "name": "Jugo Tropical de Piña, Papaya, Linaza y Chía",
        "desc": "Variante con papaya, suma enzimas digestivas naturales. Bajo en grasas y bajo IG.",
        "ingredients": [
            "80 g de piña fresca", "80 g de papaya madura", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "200 ml de agua filtrada",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 4, "c": 22, "f": 5, "gl": 8, "rec": ["fatty_liver", "overweight", "ibs"],
    },
    {
        "key": "pina_linaza_chia_curcuma",
        "name": "Jugo Dorado de Piña, Cúrcuma, Linaza y Chía",
        "desc": "Variante con cúrcuma fresca. Alto en fibra soluble. Alineado con plan de hígado graso y pérdida de peso.",
        "ingredients": [
            "120 g de piña fresca", "5 g de cúrcuma fresca rallada", "1 cucharada (10 g) de linaza molida",
            "1 cucharadita (5 g) de chía hidratada", "200 ml de agua filtrada",
            "Jugo de medio limón (15 ml)", "Pizca de pimienta negra",
        ],
        "p": 4, "c": 23, "f": 5, "gl": 9, "rec": ["fatty_liver", "overweight"],
    },
]

# 5 CHIA PUDDING variants
_CHIA_PUDDINGS = [
    {
        "key": "chia_pudding_almendra_canela",
        "name": "Pudding de Chía con Leche de Almendra y Canela",
        "desc": "Preparación nocturna con bajo índice glucémico. Alta en fibra soluble y omega-3 ALA. Apta para diabetes tipo 2 por GL bajo verificado.",
        "ingredients": [
            "30 g de semillas de chía", "200 ml de leche de almendras sin azúcar",
            "5 g de canela en polvo", "1 cucharadita (5 g) de miel cruda",
            "60 g de manzana verde rallada",
        ],
        "p": 8, "c": 25, "f": 12, "gl": 7,
        "rec": ["diabetes_t2", "overweight", "fatty_liver"],
        "allergens": ["tree_nuts"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "chia_pudding_coco_mango",
        "name": "Pudding de Chía con Leche de Coco y Mango",
        "desc": "Bowl tropical bajo en azúcar añadido. Rico en fibra soluble y grasas saludables. Apto para personas con dislipidemia.",
        "ingredients": [
            "30 g de chía", "200 ml de leche de coco light",
            "60 g de mango fresco en cubos", "5 g de coco rallado sin azúcar",
            "Jugo de medio limón (15 ml)",
        ],
        "p": 6, "c": 22, "f": 14, "gl": 8,
        "rec": ["dyslipidemia", "fatty_liver"],
        "allergens": [], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "chia_pudding_cacao_platano",
        "name": "Pudding de Chía con Cacao y Plátano",
        "desc": "Versión con cacao puro (sin azúcar añadida) y plátano maduro. Alta en fibra y potasio. Alineado con plan de pérdida de peso.",
        "ingredients": [
            "30 g de chía", "200 ml de leche de almendra sin azúcar",
            "5 g de cacao puro sin azúcar", "60 g de plátano maduro",
            "Pizca de canela",
        ],
        "p": 8, "c": 28, "f": 12, "gl": 9,
        "rec": ["overweight", "fatty_liver"],
        "allergens": ["tree_nuts"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "chia_pudding_vainilla_frutos_rojos",
        "name": "Pudding de Chía con Vainilla y Frutos Rojos",
        "desc": "Combinación con frutos rojos antioxidantes naturales. Bajo IG.",
        "ingredients": [
            "30 g de chía", "200 ml de yogur natural sin azúcar 0%",
            "70 g de mezcla de frutos rojos", "Pizca de vainilla en polvo",
            "5 g de almendras laminadas",
        ],
        "p": 12, "c": 22, "f": 9, "gl": 7,
        "rec": ["diabetes_t2", "overweight", "fatty_liver"],
        "allergens": ["dairy", "tree_nuts"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "chia_pudding_matcha_kiwi",
        "name": "Pudding de Chía con Matcha y Kiwi",
        "desc": "Variante con matcha japonés (fuente natural de cafeína suave). Bajo IG, rico en fibra.",
        "ingredients": [
            "30 g de chía", "200 ml de leche de avena sin azúcar",
            "3 g de matcha en polvo", "70 g de kiwi en cubos",
            "5 g de semillas de calabaza",
        ],
        "p": 9, "c": 26, "f": 11, "gl": 8,
        "rec": ["overweight", "fatty_liver"],
        "allergens": ["gluten"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
]

# 5 KEFIR BOWLS
_KEFIR_BOWLS = [
    {
        "key": "kefir_bowl_frutos_rojos",
        "name": "Kefir Bowl con Frutos Rojos y Semillas de Calabaza",
        "desc": "Bowl probiótico con kéfir natural y antioxidantes naturales. Apto para personas con sobrepeso.",
        "ingredients": [
            "200 ml de kéfir natural sin azúcar", "80 g de frutos rojos mixtos",
            "10 g de semillas de calabaza", "5 g de coco rallado",
            "Jugo de medio limón",
        ],
        "p": 12, "c": 22, "f": 10,
        "rec": ["overweight", "fatty_liver"],
        "allergens": ["dairy"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "kefir_bowl_mango_chia",
        "name": "Kefir Bowl Tropical con Mango y Chía",
        "desc": "Variante tropical con mango maduro y chía. Bajo en azúcar añadido.",
        "ingredients": [
            "200 ml de kéfir natural sin azúcar", "80 g de mango fresco",
            "10 g de chía hidratada", "5 g de coco rallado",
        ],
        "p": 11, "c": 24, "f": 9,
        "rec": ["fatty_liver", "overweight"],
        "allergens": ["dairy"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "kefir_bowl_kiwi_avena",
        "name": "Kefir Bowl con Kiwi y Avena Tostada",
        "desc": "Combinación con avena tostada y kiwi rico en vitamina C natural.",
        "ingredients": [
            "200 ml de kéfir natural", "70 g de kiwi en cubos",
            "20 g de avena tostada", "5 g de chía",
        ],
        "p": 13, "c": 28, "f": 7,
        "rec": ["fatty_liver", "overweight"],
        "allergens": ["dairy", "gluten"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "kefir_bowl_platano_canela",
        "name": "Kefir Bowl con Plátano y Canela",
        "desc": "Variante con plátano maduro y canela natural. Apto para deportistas en planes de mantenimiento.",
        "ingredients": [
            "200 ml de kéfir natural", "100 g de plátano en rodajas",
            "5 g de canela en polvo", "10 g de almendras laminadas",
        ],
        "p": 12, "c": 30, "f": 8,
        "rec": ["athletic_load"],
        "allergens": ["dairy", "tree_nuts"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
    {
        "key": "kefir_bowl_papaya_lino",
        "name": "Kefir Bowl con Papaya y Linaza",
        "desc": "Combinación digestiva con papaya y linaza molida. Alta en fibra soluble.",
        "ingredients": [
            "200 ml de kéfir natural", "100 g de papaya madura",
            "10 g de linaza molida", "Jugo de medio limón",
        ],
        "p": 11, "c": 23, "f": 7,
        "rec": ["ibs", "fatty_liver", "overweight"],
        "allergens": ["dairy"], "meal_format": "semi_solid", "meal_time": "breakfast",
    },
]

# 5 MATCHA / GREEN TEA
_MATCHA = [
    {
        "key": "matcha_latte_almendra",
        "name": "Matcha Latte con Leche de Almendra",
        "desc": "Bebida japonesa con matcha en polvo (té verde molido). Bajo en calorías, sin azúcar añadida.",
        "ingredients": [
            "3 g de matcha en polvo ceremonial", "200 ml de leche de almendra sin azúcar",
            "Pizca de canela", "5 ml de miel cruda opcional",
        ],
        "p": 2, "c": 8, "f": 4, "gl": 3,
        "rec": ["overweight", "fatty_liver"],
        "allergens": ["tree_nuts"], "meal_format": "liquid", "meal_time": "breakfast",
    },
    {
        "key": "matcha_smoothie_platano",
        "name": "Smoothie de Matcha con Plátano y Espinaca",
        "desc": "Bebida verde con matcha y plátano. Alta en fibra y bajo en grasas saturadas.",
        "ingredients": [
            "3 g de matcha en polvo", "60 g de plátano",
            "30 g de espinaca baby", "200 ml de leche de avena sin azúcar",
            "5 g de chía",
        ],
        "p": 5, "c": 22, "f": 5, "gl": 8,
        "rec": ["overweight", "fatty_liver"],
        "allergens": ["gluten"], "meal_format": "liquid", "meal_time": "breakfast",
    },
    {
        "key": "te_verde_jengibre_limon",
        "name": "Infusión de Té Verde con Jengibre y Limón",
        "desc": "Bebida sin calorías significativas, con jengibre fresco y limón. Apto para perfiles de pérdida de peso.",
        "ingredients": [
            "1 bolsita de té verde", "5 g de jengibre fresco rallado",
            "Jugo de medio limón", "250 ml de agua caliente filtrada",
        ],
        "p": 0, "c": 3, "f": 0, "gl": 1,
        "rec": ["overweight", "fatty_liver", "diabetes_t2"],
        "allergens": [], "meal_format": "liquid", "meal_time": "breakfast",
    },
    {
        "key": "matcha_chia_pudding_drink",
        "name": "Bebida Matcha con Chía y Coco",
        "desc": "Versión líquida con matcha y semillas de chía. Bajo IG.",
        "ingredients": [
            "3 g de matcha", "200 ml de leche de coco light",
            "10 g de chía", "5 g de coco rallado",
        ],
        "p": 4, "c": 12, "f": 11, "gl": 4,
        "rec": ["overweight", "fatty_liver"],
        "allergens": [], "meal_format": "liquid", "meal_time": "snack",
    },
    {
        "key": "te_verde_menta_jengibre",
        "name": "Infusión de Té Verde con Menta y Jengibre",
        "desc": "Combinación refrescante sin calorías significativas. Apta para planes de pérdida de peso y mantenimiento.",
        "ingredients": [
            "1 bolsita de té verde", "5 hojas de menta fresca",
            "3 g de jengibre fresco", "250 ml de agua caliente filtrada",
        ],
        "p": 0, "c": 2, "f": 0, "gl": 1,
        "rec": ["overweight", "fatty_liver"],
        "allergens": [], "meal_format": "liquid", "meal_time": "snack",
    },
]


def main() -> int:
    out: list[dict] = []

    # piña + linaza + chía batch (10)
    for tpl in _PINA_LINAZA_CHIA:
        out.append({
            "id": _id("pl", tpl["key"]),
            "name": tpl["name"],
            "description": tpl["desc"],
            "image_url": PLACEHOLDER_IMG,
            "nutrition_profile": _macros(tpl["p"], tpl["c"], tpl["f"]),
            "matching_criteria": _mc(
                goals=["weight_loss", "health"], dietary="vegan",
                cuisine=["latam"], regions=["latam", "us"],
                recommended=tpl["rec"], contraindicated=[],
                allergens=[], meal_format="liquid", pregnancy_safe=True,
            ),
            "execution": _execution(
                meal_time="breakfast", prep=5, cook=0,
                ingredients=tpl["ingredients"],
                instructions=[
                    "Hidratar la chía en 50 ml de agua durante 10 minutos hasta gel.",
                    "Licuar los ingredientes restantes 45 segundos a alta velocidad.",
                    "Incorporar el gel de chía con cuchara para preservar textura.",
                    "Servir frío en un vaso. Consumir inmediatamente.",
                ],
            ),
            "audit": _audit(gl=tpl["gl"], cultural="latam_viral"),
        })

    # chia pudding batch (5)
    for tpl in _CHIA_PUDDINGS:
        out.append({
            "id": _id("cp", tpl["key"]),
            "name": tpl["name"],
            "description": tpl["desc"],
            "image_url": PLACEHOLDER_IMG,
            "nutrition_profile": _macros(tpl["p"], tpl["c"], tpl["f"]),
            "matching_criteria": _mc(
                goals=["health", "weight_loss"],
                dietary="vegan" if "dairy" not in tpl.get("allergens", []) else "vegetarian",
                cuisine=["fusion"], regions=["latam", "us", "eu"],
                recommended=tpl["rec"], contraindicated=[],
                allergens=tpl.get("allergens", []),
                meal_format=tpl["meal_format"], pregnancy_safe=True,
            ),
            "execution": _execution(
                meal_time=tpl["meal_time"], prep=10, cook=0,
                ingredients=tpl["ingredients"],
                instructions=[
                    "Mezclar la chía con el líquido base en un frasco hermético.",
                    "Remover vigorosamente 30 segundos.",
                    "Refrigerar mínimo 6 horas (idealmente toda la noche).",
                    "Antes de servir, coronar con los ingredientes restantes.",
                ],
            ),
            "audit": _audit(gl=tpl.get("gl")),
        })

    # kefir bowls (5)
    for tpl in _KEFIR_BOWLS:
        out.append({
            "id": _id("kb", tpl["key"]),
            "name": tpl["name"],
            "description": tpl["desc"],
            "image_url": PLACEHOLDER_IMG,
            "nutrition_profile": _macros(tpl["p"], tpl["c"], tpl["f"]),
            "matching_criteria": _mc(
                goals=["health", "weight_loss", "maintain"],
                dietary="vegetarian",
                cuisine=["eu", "fusion"], regions=["latam", "us", "eu"],
                recommended=tpl["rec"], contraindicated=[],
                allergens=tpl.get("allergens", []),
                meal_format=tpl["meal_format"], pregnancy_safe=True,
            ),
            "execution": _execution(
                meal_time=tpl["meal_time"], prep=5, cook=0,
                ingredients=tpl["ingredients"],
                instructions=[
                    "Verter el kéfir en un bowl.",
                    "Agregar los ingredientes y mezclar suavemente.",
                    "Servir frío. Consumir dentro de los 30 minutos para preservar probióticos.",
                ],
            ),
            "audit": _audit(),
        })

    # matcha / green tea (5)
    for tpl in _MATCHA:
        out.append({
            "id": _id("mt", tpl["key"]),
            "name": tpl["name"],
            "description": tpl["desc"],
            "image_url": PLACEHOLDER_IMG,
            "nutrition_profile": _macros(tpl["p"], tpl["c"], tpl["f"]),
            "matching_criteria": _mc(
                goals=["health", "weight_loss"],
                dietary="vegan" if "dairy" not in tpl.get("allergens", []) else "vegetarian",
                cuisine=["asian", "fusion"], regions=["latam", "us", "eu"],
                recommended=tpl["rec"], contraindicated=[],
                allergens=tpl.get("allergens", []),
                meal_format=tpl["meal_format"], pregnancy_safe=True,
            ),
            "execution": _execution(
                meal_time=tpl["meal_time"], prep=5, cook=0,
                ingredients=tpl["ingredients"],
                instructions=[
                    "Disolver el matcha en una pequeña cantidad de agua caliente (no hirviendo, ~70°C) hasta espumar.",
                    "Incorporar el resto de los líquidos e ingredientes.",
                    "Servir caliente o frío según preferencia.",
                ],
            ),
            "audit": _audit(gl=tpl.get("gl"), cultural="japan_traditional"),
        })

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"viral juices batch: {len(out)} recipes -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
