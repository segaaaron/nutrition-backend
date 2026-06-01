"""Catalog schema migration v1 (camelCase + minimal) → v2 (snake_case + extended).

Idempotent. Backup at `data/meals/nova_meals_catalog.cleaned.json.bak` (preserved).
Writes to same file path in-place. ASCII-safe JSON, ensure_ascii=False, indent=2.

New schema (universal snake_case, English keys; ES values preserved in
name/description/ingredients):

{
  "id": str,                                  # unchanged
  "name": str,                                # ES, unchanged
  "description": str,                         # ES, unchanged
  "image_url": str | null,                    # NEW — placeholder GCS URL
  "nutrition_profile": {
    "calories": int,                          # was nutritionProfile.calories
    "macros": {
      "protein_g": int,                       # was proteinG
      "carbs_g": int,                         # was carbsG
      "fat_g": int,                           # was fatG
      "fiber_g": int,                         # NEW (0 default)
      "sugar_g": int,                         # NEW (0 default)
      "sat_fat_g": int,                       # NEW (0 default)
      "sodium_mg": int                        # NEW (0 default)
    },
    "micronutrients": {                       # NEW (all nullable, backfilled later)
      "gi": int | null,
      "gl": float | null,
      "potassium_mg": int | null,
      "phosphorus_mg": int | null,
      "iron_mg": float | null,
      "heme_pct": float | null,
      "calcium_mg": int | null,
      "omega3_mg": int | null,
      "folate_ug": int | null
    }
  },
  "matching_criteria": {
    "target_goals": list[str],                # was targetGoals
    "suitable_for_activity": list[str],       # was suitableForActivity
    "recommended_for_conditions": list[str],  # was recommendedForConditions
    "contraindicated_conditions": list[str],  # was contraindicatedConditions
    "allergens": list[str],                   # unchanged
    "regions": list[str],                     # unchanged
    "dietary_pattern": str,                   # NEW (default "omnivore")
    "cuisine_region": list[str],              # NEW (default ["latam"])
    "meal_format": str,                       # NEW (default "solid")
    "pregnancy_safe": bool                    # NEW (default false — deny by default)
  },
  "execution": {
    "meal_time": str,                         # was mealTime
    "prep_time_minutes": int,                 # was prepTimeMinutes
    "cook_time_minutes": int,                 # NEW (0 default)
    "image_url": null,                        # was firebaseImageUrl (deprecated; moved to top-level)
    "ingredients": list[str],                 # ES, unchanged
    "instructions": list[str],                # ES, unchanged
    "servings": int,                          # NEW (1 default)
    "source_catalog": str | null              # unchanged
  },
  "audit": {                                  # was _audit (drop leading underscore)
    "regions_inferred": ... ,                 # preserved
    "patches": [...],                         # preserved if present
    "schema_version": "v2",                   # NEW
    "macro_consistency_pct": float,           # NEW (computed)
    "migrated_at": "2026-06-01"               # NEW
  }
}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parent.parent / "data" / "meals" / "nova_meals_catalog.cleaned.json"

PLACEHOLDER_IMAGE = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"

# Cuisine region inference from existing recipe name + ingredients keywords.
# Default LatAm baseline (current catalog is LatAm-only).
_CUISINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "latam": (
        "tortilla", "frijol", "frijoles", "plátano", "platano", "yuca", "maíz",
        "maiz", "arepa", "tamale", "tamal", "ceviche", "guacamole", "salsa verde",
        "chicharrón", "chimichurri", "milanesa", "pico de gallo", "aji", "ají",
        "mole", "tacos", "quesadilla", "empanada", "horchata", "tepache",
    ),
    "mediterranean": (
        "hummus", "olivo", "feta", "halloumi", "tahini", "couscous", "falafel",
        "tabbouleh", "ouzo", "ratatouille", "moussaka",
    ),
    "asian": (
        "sushi", "miso", "soja", "soy sauce", "edamame", "tofu", "tempeh",
        "ramen", "udon", "kimchi", "wasabi", "nori", "matcha",
    ),
    "middle_eastern": ("kebab", "shawarma", "baba ganoush", "labneh", "harissa"),
    "north_american": (
        "burger", "hamburguesa", "pancake", "panqueque", "waffle", "bagel",
        "peanut butter", "mantequilla de maní",
    ),
}


def _infer_cuisine_region(name: str, description: str, ingredients: list[str]) -> list[str]:
    text = " ".join([name, description] + ingredients).lower()
    matched = [region for region, kws in _CUISINE_KEYWORDS.items() if any(k in text for k in kws)]
    return matched or ["latam"]  # default if no signal


def _infer_dietary_pattern(name: str, ingredients: list[str], allergens: list[str]) -> str:
    text = " ".join([name] + ingredients).lower()
    # Strict vegan markers (no animal products in ingredients)
    animal = ("pollo", "carne", "res", "cerdo", "pescado", "atún", "atun", "salmón",
              "salmon", "huevo", "leche", "yogur", "queso", "mantequilla", "tocino",
              "jamón", "jamon", "pavo", "cordero", "camarón", "camaron", "langosta",
              "chicken", "beef", "pork", "fish", "tuna", "salmon", "egg", "milk",
              "yogurt", "cheese", "butter", "bacon", "ham", "turkey", "shrimp",
              "marisco", "mariscos", "mejillón", "mejillon", "almeja")
    has_animal = any(a in text for a in animal)
    if not has_animal:
        return "vegan"
    # Pescatarian = fish but no meat
    meat = ("pollo", "carne", "res", "cerdo", "tocino", "jamón", "jamon", "pavo",
            "cordero", "chicken", "beef", "pork", "bacon", "ham", "turkey")
    fish = ("pescado", "atún", "atun", "salmón", "salmon", "camarón", "camaron",
            "langosta", "fish", "tuna", "salmon", "shrimp", "marisco", "mariscos",
            "mejillón", "mejillon", "almeja")
    has_meat = any(m in text for m in meat)
    has_fish = any(f in text for f in fish)
    if has_fish and not has_meat:
        return "pescatarian"
    # Vegetarian = dairy/egg but no meat or fish
    if not has_meat and not has_fish:
        return "vegetarian"
    return "omnivore"


_LIQUID_RE = __import__("re").compile(
    r"\b(jugo|batido|smoothie|licuado|bebida|infusi[oó]n|t[eé]\s+(?:verde|negro|matcha|chai|caliente|frio|fr[ií]o)|kombucha|kefir|leche\s+dorada|golden\s+milk|matcha\s+latte)\b",
    __import__("re").IGNORECASE,
)
_SEMI_SOLID_RE = __import__("re").compile(
    r"\b(pudd?[ií]n|pudding|yogur|yoghurt|mousse|pur[eé]|crema|sopa|chia\s+pudding|overnight\s+oats|a[cç]a[ií]\s+bowl|bowl\s+de\s+a[cç]a[ií])\b",
    __import__("re").IGNORECASE,
)


def _infer_meal_format(name: str, description: str) -> str:
    text = name + " " + description
    if _LIQUID_RE.search(text):
        return "liquid"
    if _SEMI_SOLID_RE.search(text):
        return "semi_solid"
    return "solid"


def _macro_consistency_pct(kcal: int, p: int, c: int, f: int) -> float:
    if kcal <= 0:
        return 0.0
    derived = 4 * p + 4 * c + 9 * f
    return round(abs(derived - kcal) / kcal, 4)


def _migrate_recipe(r: dict[str, Any]) -> dict[str, Any]:
    """Return v2 dict. Idempotent — if already v2, return as-is."""
    audit_in = r.get("audit") or r.get("_audit") or {}
    if audit_in.get("schema_version") == "v2":
        return r  # already migrated

    np_in = r.get("nutritionProfile") or r.get("nutrition_profile") or {}
    macros_in = np_in.get("macros", {})
    micros_in = np_in.get("micronutrients", {})

    mc_in = r.get("matchingCriteria") or r.get("matching_criteria") or {}
    ex_in = r.get("execution") or {}

    name = r.get("name", "")
    description = r.get("description", "")
    ingredients = ex_in.get("ingredients") or []
    allergens = mc_in.get("allergens") or []

    kcal = int(np_in.get("calories") or 0)
    p = int(macros_in.get("proteinG") if "proteinG" in macros_in else macros_in.get("protein_g") or 0)
    c = int(macros_in.get("carbsG") if "carbsG" in macros_in else macros_in.get("carbs_g") or 0)
    f = int(macros_in.get("fatG") if "fatG" in macros_in else macros_in.get("fat_g") or 0)

    return {
        "id": r["id"],
        "name": name,
        "description": description,
        "image_url": r.get("image_url") or PLACEHOLDER_IMAGE,
        "nutrition_profile": {
            "calories": kcal,
            "macros": {
                "protein_g": p,
                "carbs_g": c,
                "fat_g": f,
                "fiber_g": int(macros_in.get("fiber_g") or macros_in.get("fiberG") or 0),
                "sugar_g": int(macros_in.get("sugar_g") or macros_in.get("sugarG") or 0),
                "sat_fat_g": int(macros_in.get("sat_fat_g") or macros_in.get("satFatG") or 0),
                "sodium_mg": int(macros_in.get("sodium_mg") or macros_in.get("sodiumMg") or 0),
            },
            "micronutrients": {
                "gi": micros_in.get("gi"),
                "gl": micros_in.get("gl"),
                "potassium_mg": micros_in.get("potassium_mg"),
                "phosphorus_mg": micros_in.get("phosphorus_mg"),
                "iron_mg": micros_in.get("iron_mg"),
                "heme_pct": micros_in.get("heme_pct"),
                "calcium_mg": micros_in.get("calcium_mg"),
                "omega3_mg": micros_in.get("omega3_mg"),
                "folate_ug": micros_in.get("folate_ug"),
            },
        },
        "matching_criteria": {
            "target_goals": mc_in.get("targetGoals") or mc_in.get("target_goals") or [],
            "suitable_for_activity": mc_in.get("suitableForActivity") or mc_in.get("suitable_for_activity") or [],
            "recommended_for_conditions": mc_in.get("recommendedForConditions") or mc_in.get("recommended_for_conditions") or [],
            "contraindicated_conditions": mc_in.get("contraindicatedConditions") or mc_in.get("contraindicated_conditions") or [],
            "allergens": allergens,
            "regions": mc_in.get("regions") or ["latam"],
            "dietary_pattern": mc_in.get("dietary_pattern") or _infer_dietary_pattern(name, ingredients, allergens),
            "cuisine_region": mc_in.get("cuisine_region") or _infer_cuisine_region(name, description, ingredients),
            "meal_format": mc_in.get("meal_format") or _infer_meal_format(name, description),
            "pregnancy_safe": bool(mc_in.get("pregnancy_safe", False)),
        },
        "execution": {
            "meal_time": ex_in.get("mealTime") or ex_in.get("meal_time") or "lunch",
            "prep_time_minutes": int(ex_in.get("prepTimeMinutes") or ex_in.get("prep_time_minutes") or 0),
            "cook_time_minutes": int(ex_in.get("cookTimeMinutes") or ex_in.get("cook_time_minutes") or 0),
            "image_url": ex_in.get("firebaseImageUrl") or ex_in.get("image_url"),
            "ingredients": ingredients,
            "instructions": ex_in.get("instructions") or [],
            "servings": int(ex_in.get("servings") or 1),
            "source_catalog": ex_in.get("source_catalog"),
        },
        "audit": {
            **{k: v for k, v in audit_in.items() if not k.startswith("_")},
            "schema_version": "v2",
            "macro_consistency_pct": _macro_consistency_pct(kcal, p, c, f),
            "migrated_at": "2026-06-01",
        },
    }


def main() -> int:
    if not CATALOG.exists():
        print(f"missing {CATALOG}", file=sys.stderr)
        return 2

    data = json.loads(CATALOG.read_text())
    if not isinstance(data, list):
        print("catalog must be a JSON array", file=sys.stderr)
        return 2

    migrated_count = 0
    skipped_count = 0
    for i, r in enumerate(data):
        new_r = _migrate_recipe(r)
        if new_r is r:
            skipped_count += 1
            continue
        data[i] = new_r
        migrated_count += 1

    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"migrated: {migrated_count} | already_v2: {skipped_count} | total: {len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
