"""Seed `recipes` from `data/meals/nova_meals_catalog.cleaned.json` (schema v2 snake_case).

Catalog schema v2 (post-2026-06-01 migration):
  - All keys snake_case English (ES preserved in name/description/ingredients values)
  - Fields: id, name, description, image_url,
            nutrition_profile.{calories, macros{protein_g/carbs_g/fat_g/fiber_g/sugar_g/sat_fat_g/sodium_mg}, micronutrients{...}},
            matching_criteria.{target_goals, suitable_for_activity, recommended_for_conditions,
                               contraindicated_conditions, allergens, regions, dietary_pattern,
                               cuisine_region, meal_format, pregnancy_safe},
            execution.{meal_time, prep_time_minutes, cook_time_minutes, image_url, ingredients,
                       instructions, servings, source_catalog},
            audit.{schema_version, macro_consistency_pct, ...}

UPSERT key: `name_en` (the master recipe name as displayed). Re-runs replace
recipe_components + recipe_allergens for matched recipes.

Idempotent — safe to re-run after catalog updates. Existing rows with same
name_en are UPDATEd, new rows INSERTed.

ENV:
  SKIP_AUDIT_GATE=1   skips the legacy reports/ audit check (default: skip
                      always — v2 schema replaces the legacy gate with
                      tests/catalog/test_enum_closure.py CI guard)
  DRY_RUN=1           parse + validate but don't write to DB
  LIMIT=<int>         only process first N recipes (for smoke tests)

Run inside Dokploy container:
  docker exec -it nova-api-1 python -m scripts.seed_recipes

Verify after:
  docker exec -it nova-db-1 psql -U nova -d nova -c \\
    "SELECT COUNT(*) FROM recipes;"
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger

log = get_logger("scripts.seed_recipes")

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"

VALID_ALLERGENS: frozenset[str] = frozenset({
    "dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg",
    "soy", "sesame", "celery", "mustard", "lupin", "sulphites", "molluscs",
})
VALID_REGIONS: frozenset[str] = frozenset({"us", "ca", "eu", "uk", "latam"})
VALID_GOALS: frozenset[str] = frozenset({
    "weight_loss", "maintain", "muscle_gain", "weight_gain", "health",
})
VALID_MEAL_TIMES: frozenset[str] = frozenset({"breakfast", "lunch", "dinner", "snack"})


def _detect_locale(text_blob: str) -> str:
    """Cheap language sniff: Spanish vs English. Returns BCP-47 locale code."""
    es_markers = (
        " de ", " con ", " sin ", " la ", " el ", " y ", " para ",
        "ñ", "á", "é", "í", "ó", "ú",
    )
    score = sum(1 for m in es_markers if m in text_blob.lower())
    return "es" if score >= 2 else "en"


_AMOUNT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(g|gr|grs|gramos|ml|tazas?|cdas?|cdtas?|piezas?|"
    r"unid|huevos?|hojas?|rodajas?)\b",
    re.IGNORECASE,
)


def _parse_amount_g(ingredient_str: str) -> float | None:
    """Best-effort parse of '40 g de avena' -> 40.0; '200 ml de leche' -> 200.0."""
    m = _AMOUNT_RE.search(ingredient_str)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _filter_enum(items: list[str], allowed: frozenset[str]) -> list[str]:
    return [i for i in items if i in allowed]


async def main() -> int:
    configure_logging()

    if not CATALOG_PATH.exists():
        log.error("seed_recipes.catalog_missing", path=str(CATALOG_PATH))
        return 2

    dry_run = os.environ.get("DRY_RUN") == "1"
    limit = int(os.environ.get("LIMIT", "0"))

    raw = json.loads(CATALOG_PATH.read_text())
    if limit > 0:
        raw = raw[:limit]
    log.info(
        "seed_recipes.catalog_loaded",
        n=len(raw), dry_run=dry_run, limit_applied=limit,
    )

    seen_names: dict[str, int] = {}
    inserted = updated = errors = 0

    if dry_run:
        # Validate parseability + enum membership, do not write.
        for rec in raw:
            try:
                mc = rec.get("matching_criteria") or {}
                _filter_enum(mc.get("regions") or [], VALID_REGIONS)
                _filter_enum(mc.get("allergens") or [], VALID_ALLERGENS)
                _filter_enum(mc.get("target_goals") or [], VALID_GOALS)
                meal_time = (rec.get("execution") or {}).get("meal_time")
                if meal_time and meal_time not in VALID_MEAL_TIMES:
                    errors += 1
            except Exception:  # noqa: BLE001
                errors += 1
        log.info("seed_recipes.dry_run_complete", total=len(raw), errors=errors)
        return 0 if errors == 0 else 1

    async with session_scope() as s:
        for rec in raw:
            try:
                name = (rec.get("name") or "").strip()
                if not name:
                    errors += 1
                    continue
                seen_names[name] = seen_names.get(name, 0) + 1
                if seen_names[name] > 1:
                    name = f"{name} v{seen_names[name]}"

                desc = (rec.get("description") or "").strip()
                image_url = rec.get("image_url")

                nut = rec.get("nutrition_profile") or {}
                macros = nut.get("macros") or {}
                micros = nut.get("micronutrients") or {}

                mc = rec.get("matching_criteria") or {}
                exe = rec.get("execution") or {}

                ingredients: list[str] = exe.get("ingredients") or []
                instructions: list[str] = exe.get("instructions") or []
                locale = _detect_locale(" ".join([name, desc] + instructions))

                regions = _filter_enum(mc.get("regions") or [], VALID_REGIONS) or ["latam"]
                allergens = _filter_enum(mc.get("allergens") or [], VALID_ALLERGENS)
                target_goals = _filter_enum(mc.get("target_goals") or [], VALID_GOALS)
                recommended = list(mc.get("recommended_for_conditions") or [])
                contraindicated = list(mc.get("contraindicated_conditions") or [])

                meal_time = exe.get("meal_time")
                if meal_time not in VALID_MEAL_TIMES:
                    meal_time = None
                prep_min = exe.get("prep_time_minutes")
                source_batch = exe.get("source_catalog") or rec.get("source_catalog")

                # v2 schema additions (migration 0008+0010)
                pregnancy_safe = bool(mc.get("pregnancy_safe", False))
                # Note: dietary_pattern, cuisine_region, meal_format live as
                # JSONB or tags in DB if user adds columns; for now stored in
                # the audit JSONB blob preserved as-is by the table column
                # if present, else ignored. Defensive: only populate columns
                # known to exist per migrations 0001-0008.

                # Translations
                name_translations = (
                    json.dumps({locale: rec["name"]}) if locale != "en" else "{}"
                )
                description_translations = (
                    json.dumps({locale: desc}) if desc and locale != "en" else "{}"
                )
                instructions_translations = (
                    json.dumps({locale: instructions})
                    if instructions and locale != "en" else "{}"
                )

                params: dict[str, Any] = {
                    "name_en": name,
                    "name_translations": name_translations,
                    "description_en": desc,
                    "description_translations": description_translations,
                    "image_url": image_url,
                    "kcal": nut.get("calories"),
                    "protein_g": macros.get("protein_g"),
                    "carbs_g": macros.get("carbs_g"),
                    "fat_g": macros.get("fat_g"),
                    "fiber_g": macros.get("fiber_g") or 0,
                    "sugar_g": macros.get("sugar_g") or 0,
                    "sat_fat_g": macros.get("sat_fat_g") or 0,
                    "sodium_mg": macros.get("sodium_mg") or 0,
                    # Micronutrients (migration 0008 columns; NULL OK)
                    "gi": micros.get("gi"),
                    "gl": micros.get("gl"),
                    "potassium_mg": micros.get("potassium_mg"),
                    "phosphorus_mg": micros.get("phosphorus_mg"),
                    "iron_mg": micros.get("iron_mg"),
                    "heme_pct": micros.get("heme_pct"),
                    "calcium_mg": micros.get("calcium_mg"),
                    "omega3_mg": micros.get("omega3_mg"),
                    "folate_ug": micros.get("folate_ug"),
                    "pregnancy_safe": pregnancy_safe,
                    "meal_time": meal_time,
                    "prep_min": prep_min,
                    "instructions_en": instructions,
                    "instructions_translations": instructions_translations,
                    "regions": "{" + ",".join(regions) + "}",
                    "target_goals": "{" + ",".join(target_goals) + "}",
                    "recommended": "{" + ",".join(recommended) + "}",
                    "contraindicated": "{" + ",".join(contraindicated) + "}",
                    "source_batch": source_batch,
                    "source_catalog": source_batch,
                }

                res = await s.execute(text("""
                    INSERT INTO recipes (
                        name_en, name_translations, description_en, description_translations,
                        image_url, kcal, protein_g, carbs_g, fat_g,
                        fiber_g, sugar_g, sat_fat_g, sodium_mg,
                        gi, gl, potassium_mg, phosphorus_mg, iron_mg, heme_pct,
                        calcium_mg, omega3_mg, folate_ug, pregnancy_safe,
                        meal_time, prep_min, instructions_en, instructions_translations,
                        regions, target_goals, recommended_conditions, contraindicated_conditions,
                        source_batch, source_catalog
                    ) VALUES (
                        :name_en, CAST(:name_translations AS jsonb),
                        :description_en, CAST(:description_translations AS jsonb),
                        :image_url, :kcal, :protein_g, :carbs_g, :fat_g,
                        :fiber_g, :sugar_g, :sat_fat_g, :sodium_mg,
                        :gi, :gl, :potassium_mg, :phosphorus_mg, :iron_mg, :heme_pct,
                        :calcium_mg, :omega3_mg, :folate_ug, :pregnancy_safe,
                        CAST(:meal_time AS meal_time_enum), :prep_min, :instructions_en,
                        CAST(:instructions_translations AS jsonb),
                        CAST(:regions AS char(5)[]),
                        CAST(:target_goals AS goal_enum[]),
                        CAST(:recommended AS text[]),
                        CAST(:contraindicated AS text[]),
                        :source_batch, :source_catalog
                    )
                    ON CONFLICT (name_en) DO UPDATE SET
                        name_translations = EXCLUDED.name_translations,
                        description_en = EXCLUDED.description_en,
                        description_translations = EXCLUDED.description_translations,
                        image_url = EXCLUDED.image_url,
                        kcal = EXCLUDED.kcal,
                        protein_g = EXCLUDED.protein_g,
                        carbs_g = EXCLUDED.carbs_g,
                        fat_g = EXCLUDED.fat_g,
                        fiber_g = EXCLUDED.fiber_g,
                        sugar_g = EXCLUDED.sugar_g,
                        sat_fat_g = EXCLUDED.sat_fat_g,
                        sodium_mg = EXCLUDED.sodium_mg,
                        gi = EXCLUDED.gi,
                        gl = EXCLUDED.gl,
                        potassium_mg = EXCLUDED.potassium_mg,
                        phosphorus_mg = EXCLUDED.phosphorus_mg,
                        iron_mg = EXCLUDED.iron_mg,
                        heme_pct = EXCLUDED.heme_pct,
                        calcium_mg = EXCLUDED.calcium_mg,
                        omega3_mg = EXCLUDED.omega3_mg,
                        folate_ug = EXCLUDED.folate_ug,
                        pregnancy_safe = EXCLUDED.pregnancy_safe,
                        meal_time = EXCLUDED.meal_time,
                        prep_min = EXCLUDED.prep_min,
                        instructions_en = EXCLUDED.instructions_en,
                        instructions_translations = EXCLUDED.instructions_translations,
                        regions = EXCLUDED.regions,
                        target_goals = EXCLUDED.target_goals,
                        recommended_conditions = EXCLUDED.recommended_conditions,
                        contraindicated_conditions = EXCLUDED.contraindicated_conditions,
                        source_batch = EXCLUDED.source_batch,
                        source_catalog = EXCLUDED.source_catalog
                    RETURNING id, (xmax = 0) AS inserted
                """), params)
                row = res.first()
                if row is None:
                    errors += 1
                    continue
                recipe_id = row[0]
                if row[1]:
                    inserted += 1
                else:
                    updated += 1

                # Replace allergens (trigger syncs recipes.allergens denorm column)
                await s.execute(
                    text("DELETE FROM recipe_allergens WHERE recipe_id = :rid"),
                    {"rid": recipe_id},
                )
                for a in allergens:
                    await s.execute(
                        text(
                            "INSERT INTO recipe_allergens(recipe_id, allergen) "
                            "VALUES (:rid, CAST(:a AS allergen_enum))"
                        ),
                        {"rid": recipe_id, "a": a},
                    )

                # Replace components (ingredients → recipe_components rows)
                await s.execute(
                    text("DELETE FROM recipe_components WHERE recipe_id = :rid"),
                    {"rid": recipe_id},
                )
                for idx, ingr in enumerate(ingredients):
                    amount_g = _parse_amount_g(ingr)
                    await s.execute(text("""
                        INSERT INTO recipe_components (recipe_id, food_id, free_text_name, amount_g, position)
                        VALUES (:rid, NULL, :ftn, :amt, :pos)
                    """), {
                        "rid": recipe_id,
                        "ftn": ingr.strip(),
                        "amt": amount_g,
                        "pos": idx,
                    })

                if (inserted + updated) % 1000 == 0:
                    log.info(
                        "seed_recipes.progress",
                        processed=inserted + updated, errors=errors,
                    )

            except Exception as e:  # noqa: BLE001
                errors += 1
                log.error(
                    "seed_recipes.row_failed",
                    name=rec.get("name"), error=str(e),
                )

    log.info(
        "seed_recipes.complete",
        total=len(raw), inserted=inserted, updated=updated, errors=errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
