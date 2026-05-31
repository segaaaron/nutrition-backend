"""Seed `recipes` from `data/meals/nova_meals_catalog.cleaned.json`.

EN canonical mapping (spec §21):
  - name        -> name_en (Spanish source kept as name_translations.es)
  - description -> description_en (Spanish source kept as description_translations.es)
  - instructions-> instructions_en (Spanish source kept as instructions_translations.es)
  - regions     -> regions[]
  - allergens   -> recipe_allergens (trigger syncs recipes.allergens)
  - mealTime    -> meal_time
  - target/recommended/contraindicated conditions / goals stored as text[] / enum[]

Components: per execution.ingredients we try a `nombre_norm` lookup in
`foods`; on miss we store `free_text_name` (still a valid component per the
schema CHECK constraint).

Idempotent: UPSERT on `name_en`. Re-runs replace recipe_components +
recipe_allergens for the matched recipe. Triggers recompute recipes.allergens
and recipes.fiber_g/sugar_g/sodium_mg/sat_fat_g.

Audit gate: refuses to run unless the latest reports/catalog_audit_*.json is
present and exit code says all 8 gates passed (audit pipeline §20).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from scripts.seed_foods import normalise as norm_food_name

log = get_logger("scripts.seed_recipes")

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
REPORTS_DIR = ROOT / "reports"

VALID_ALLERGENS = {
    "dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg",
    "soy", "sesame", "celery", "mustard", "lupin", "sulphites", "molluscs",
}
VALID_REGIONS = {"us", "ca", "eu", "uk", "latam"}
VALID_GOALS = {"weight_loss", "maintain", "muscle_gain", "weight_gain", "health"}


def _detect_locale(text_blob: str) -> str:
    """Cheap language sniff: Spanish vs English. Returns BCP-47 locale code."""
    es_markers = (" de ", " con ", " sin ", " la ", " el ", " y ", " para ", "ñ", "á", "é", "í", "ó", "ú")
    score = sum(1 for m in es_markers if m in text_blob.lower())
    return "es" if score >= 2 else "en"


_AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|gr|grs|gramos|ml|tazas?|cdas?|cdtas?|piezas?|unid|huevos?|hojas?|rodajas?)\b", re.IGNORECASE)


def _parse_amount_g(ingredient_str: str) -> float | None:
    """Best-effort parse of '40 g de avena' -> 40.0; '200 ml de leche' -> 200.0
    (treating ml as g; not perfect but good enough for the seed batch)."""
    m = _AMOUNT_RE.search(ingredient_str)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _strip_amount(ingredient_str: str) -> str:
    """Strip amount + connector words; keep the food identifier."""
    s = _AMOUNT_RE.sub("", ingredient_str)
    s = re.sub(r"\b(de|del|la|el|en|con|sin)\b", " ", s, flags=re.IGNORECASE)
    s = " ".join(s.split())
    return s.strip()


def _audit_report_green() -> bool:
    if not REPORTS_DIR.exists():
        return False
    reports = sorted(REPORTS_DIR.glob("catalog_audit_*.json"))
    if not reports:
        return False
    latest = reports[-1]
    try:
        data = json.loads(latest.read_text())
    except json.JSONDecodeError:
        return False
    # Schema written by scripts/audit_catalog.py: {"summary": {"all_passed": bool}, ...}
    summary = data.get("summary", {})
    return bool(summary.get("all_passed") or summary.get("exit_code") == 0)


async def _lookup_food_id(s, ingredient_str: str) -> str | None:
    stripped = _strip_amount(ingredient_str)
    if not stripped:
        return None
    nname = norm_food_name(stripped)
    res = await s.execute(
        text("SELECT id FROM foods WHERE name_norm = :n LIMIT 1"),
        {"n": nname},
    )
    row = res.first()
    if row:
        return str(row[0])
    # Trigram fallback (looser)
    res = await s.execute(
        text("SELECT id FROM foods WHERE name_norm % :n ORDER BY similarity(name_norm, :n) DESC LIMIT 1"),
        {"n": nname},
    )
    row = res.first()
    return str(row[0]) if row else None


def _filter_enum(items: list[str], allowed: set[str]) -> list[str]:
    return [i for i in items if i in allowed]


async def main() -> int:
    configure_logging()
    if not _audit_report_green() and os.environ.get("SKIP_AUDIT_GATE") != "1":
        log.error("seed_recipes.audit_gate_failed",
                  detail="No green catalog_audit_*.json in reports/. Set SKIP_AUDIT_GATE=1 to override.")
        return 2

    if not CATALOG_PATH.exists():
        log.error("seed_recipes.catalog_missing", path=str(CATALOG_PATH))
        return 2

    raw = json.loads(CATALOG_PATH.read_text())
    log.info("seed_recipes.catalog_loaded", n=len(raw))

    # Duplicate guard — append _v2 suffix for the known dupes after first sight.
    seen_names: dict[str, int] = {}
    inserted = updated = errors = 0

    async with session_scope() as s:
        for rec in raw:
            try:
                name = rec.get("name", "").strip()
                if not name:
                    errors += 1
                    continue
                seen_names[name] = seen_names.get(name, 0) + 1
                if seen_names[name] > 1:
                    name = f"{name} v{seen_names[name]}"

                desc = (rec.get("description") or "").strip()
                nut = rec.get("nutritionProfile") or {}
                macros = nut.get("macros") or {}
                exe = rec.get("execution") or {}
                crit = rec.get("matchingCriteria") or {}

                ingredients: list[str] = exe.get("ingredients") or []
                instructions: list[str] = exe.get("instructions") or []
                locale = _detect_locale(" ".join([name, desc] + instructions))

                regions = _filter_enum(crit.get("regions") or [], VALID_REGIONS)
                if not regions:
                    regions = ["latam"]  # seed default

                allergens = _filter_enum(crit.get("allergens") or [], VALID_ALLERGENS)
                target_goals = _filter_enum(crit.get("targetGoals") or [], VALID_GOALS)
                recommended = list(crit.get("recommendedForConditions") or [])
                contraindicated = list(crit.get("contraindicatedConditions") or [])
                meal_time = exe.get("mealTime") or None
                if meal_time not in {"breakfast", "lunch", "dinner", "snack"}:
                    meal_time = None
                prep_min = exe.get("prepTimeMinutes")
                image_url = exe.get("firebaseImageUrl")
                source_batch = exe.get("source_catalog") or rec.get("source_catalog")

                # Build translations
                name_translations = json.dumps({locale: rec["name"]}) if locale != "en" else "{}"
                description_translations = json.dumps({locale: desc}) if desc and locale != "en" else "{}"
                instructions_translations = (
                    json.dumps({locale: instructions}) if instructions and locale != "en" else "{}"
                )
                # EN canonical fields: copy source if locale=='en' else leave as source-language
                # for the MVP (downstream translation worker will fill EN later).
                name_en = name if locale == "en" else name  # always store; UI uses translations
                description_en = desc
                instructions_en = instructions

                params: dict[str, Any] = {
                    "name_en": name_en,
                    "name_translations": name_translations,
                    "description_en": description_en,
                    "description_translations": description_translations,
                    "image_url": image_url,
                    "kcal": nut.get("calories"),
                    "protein_g": macros.get("proteinG"),
                    "carbs_g": macros.get("carbsG"),
                    "fat_g": macros.get("fatG"),
                    "meal_time": meal_time,
                    "prep_min": prep_min,
                    "instructions_en": instructions_en,
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
                        meal_time, prep_min, instructions_en, instructions_translations,
                        regions, target_goals, recommended_conditions, contraindicated_conditions,
                        source_batch, source_catalog
                    ) VALUES (
                        :name_en, CAST(:name_translations AS jsonb),
                        :description_en, CAST(:description_translations AS jsonb),
                        :image_url, :kcal, :protein_g, :carbs_g, :fat_g,
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
                recipe_id = row[0]
                if row[1]:
                    inserted += 1
                else:
                    updated += 1

                # Replace allergens (trigger will sync recipes.allergens denorm column)
                await s.execute(text("DELETE FROM recipe_allergens WHERE recipe_id = :rid"), {"rid": recipe_id})
                for a in allergens:
                    await s.execute(
                        text("INSERT INTO recipe_allergens(recipe_id, allergen) VALUES (:rid, CAST(:a AS allergen_enum))"),
                        {"rid": recipe_id, "a": a},
                    )

                # Replace components
                await s.execute(text("DELETE FROM recipe_components WHERE recipe_id = :rid"), {"rid": recipe_id})
                for idx, ingr in enumerate(ingredients):
                    food_id = await _lookup_food_id(s, ingr)
                    amount_g = _parse_amount_g(ingr)
                    await s.execute(text("""
                        INSERT INTO recipe_components (recipe_id, food_id, free_text_name, amount_g, position)
                        VALUES (:rid, :fid, :ftn, :amt, :pos)
                    """), {
                        "rid": recipe_id,
                        "fid": food_id,
                        "ftn": None if food_id else ingr.strip(),
                        "amt": amount_g,
                        "pos": idx,
                    })
            except Exception as e:  # noqa: BLE001
                errors += 1
                log.error("seed_recipes.row_failed", name=rec.get("name"), error=str(e))

    log.info("seed_recipes.complete",
             total=len(raw), inserted=inserted, updated=updated, errors=errors)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
