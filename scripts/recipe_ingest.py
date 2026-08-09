"""The one way a recipe enters the catalog.

PERMANENT module. Every batch script MUST insert through `ingest()`; nothing
should write to `recipes` directly.

Why this exists
---------------
Before it, each batch carried its own hardcoded nutrition table. The
2026-08-04 fatty-liver batch is the cautionary case: its private `NUT` dict
listed sugar as 0 for oats, yogurt, apple and banana, so its own validator
confirmed all 98 recipes cleared the `sugar <= 8` gate. They did not — the
numbers it validated against were fiction, and 26 of them were over the limit
the moment real USDA values landed. Every batch reinvented the same wheel and
each one got it wrong differently:

  * `nova_v4_2026_07_28` stored `kcal = 130` on snacks computing to 300-460.
  * `weight_gain_v2_2026_08_04` shipped 65 recipes with no image.
  * `bolivia_phase2_2026-08-03` shipped 24 with no `target_goals`, so Layer 1
    could never select them.
  * `fatty_liver_expansion_2026_08_04` shipped 98 with empty instructions.
  * Several inserted components AFTER nutrition, letting the aggregates trigger
    zero it back out.

The fix is structural: **a caller cannot pass nutrition at all.** There is no
`kcal=` parameter. A draft carries ingredients and prose; every number is
derived here from `ingredient_resolver` against USDA, allergens are derived
from the same components, and the row is validated before it is written.
Ordering is handled too — components are inserted first, then nutrition is
written to `recipes`, so the aggregates trigger cannot clobber it.

Usage
-----
    from recipe_ingest import RecipeDraft, ingest

    draft = RecipeDraft(
        name_en="Grilled chicken with quinoa and broccoli",
        name_es="Pollo a la plancha con quinoa y brócoli",
        description_en="High-protein lunch with complete-protein quinoa.",
        description_es="Almuerzo alto en proteína con quinoa.",
        meal_time="lunch",
        components=[("Pechuga de pollo (cruda)", 200), ("Quinoa cocida", 150),
                    ("Brócoli (crudo)", 120), ("Aceite de oliva", 10)],
        source_batch="my_batch_2026_08",
    )
    recipe_id = await ingest(conn, draft)
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backfill_recipe_metadata import (  # noqa: E402
    build_instructions,
    classify,
    derive_goals,
    derive_tags,
)
from ingredient_resolver import (  # noqa: E402
    UnresolvedIngredientError,
    compute_recipe,
    resolve_key,
)
from recompute_catalog_nutrition import (  # noqa: E402
    CEIL_COLUMNS,
    FLOOR_COLUMNS,
    OFFICIAL_BANDS,
)

_ALLERGEN_MAP_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "nutrition_reference" / "ingredient_allergens.json"
)

SUPPORTED_MARKETS = ("latam", "us", "ca")
SUPPORTED_CONDITIONS = ("fatty_liver", "pregnancy", "lactation")

# Minimum protein per slot. Below these a meal is mis-balanced whatever its
# kcal: ISSN 2017 puts intake at 1.6-2.2 g/kg/day for body-composition goals,
# which a 20 g lunch cannot reach across three meals.
MIN_PROTEIN_G = {"breakfast": 15, "lunch": 25, "dinner": 20, "snack": 5}

MIN_INSTRUCTION_STEPS = 5


class IngestError(ValueError):
    """A draft that would put wrong or incomplete data in the catalog."""


@dataclass(frozen=True, slots=True)
class RecipeDraft:
    """What a batch author supplies. Note what is absent: every nutrient.

    There is deliberately no `kcal`, `protein_g`, `sugar_g` or `allergens`
    field. Those are derived from `components`, so a batch cannot assert a
    number the ingredients do not support.
    """

    name_en: str
    name_es: str
    description_en: str
    description_es: str
    meal_time: str
    components: list[tuple[str, float]]
    source_batch: str
    # Optional — derived from the recipe's own numbers when omitted.
    target_goals: list[str] | None = None
    tags: list[str] | None = None
    instructions_en: list[str] | None = None
    instructions_es: list[str] | None = None
    regions: list[str] = field(default_factory=lambda: ["latam", "us", "ca"])
    recommended_conditions: list[str] = field(default_factory=list)
    excluded_countries: list[str] = field(default_factory=list)
    image_url: str | None = None
    prep_min: int = 20
    pregnancy_safe: bool = False
    is_vegetarian: bool = False
    is_vegan: bool = False
    verified_by: str = "recipe_ingest"


def _load_allergen_map() -> dict[str, list[str]]:
    raw = json.loads(_ALLERGEN_MAP_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _store(field_name: str, value: Decimal) -> int:
    """Directional rounding — see recompute_catalog_nutrition.

    Columns where more is worse round UP; the fiber floor rounds DOWN. Integer
    storage must never make a recipe look safer than it is.
    """
    if field_name in CEIL_COLUMNS:
        return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))
    if field_name in FLOOR_COLUMNS:
        return int(value.quantize(Decimal("1"), rounding=ROUND_FLOOR))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def derive_allergens(components: list[tuple[str, float]]) -> list[str]:
    allergen_map = _load_allergen_map()
    found: set[str] = set()
    for name, _ in components:
        found.update(allergen_map.get(resolve_key(name), ()))
    return sorted(found)


def build_row(draft: RecipeDraft) -> dict:
    """Derive every stored value from the draft. Raises on anything unusable."""
    problems: list[str] = []

    if draft.meal_time not in OFFICIAL_BANDS:
        raise IngestError(f"unknown meal_time {draft.meal_time!r}")
    if not draft.components:
        raise IngestError("a recipe with no components has untraceable nutrition")

    unknown = []
    for name, grams in draft.components:
        try:
            resolve_key(name)
        except UnresolvedIngredientError:
            unknown.append(name)
        if grams <= 0:
            problems.append(f"component {name!r} has non-positive grams ({grams})")
    if unknown:
        raise IngestError(
            f"{len(unknown)} ingredients do not resolve to USDA: {unknown}. "
            "Add them to ingredient_aliases.json or ingredient_extra_usda.json — "
            "nutrition is never defaulted to zero."
        )

    nutrition = compute_recipe(draft.components)
    row = {f: _store(f, v) for f, v in nutrition.items() if f != "iron_mg"}
    row["iron_mg"] = nutrition["iron_mg"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # kcal from the ALREADY-ROUNDED macros, so the stored value can never
    # contradict the stored macros (and satisfies ck_recipes_kcal_atwater).
    row["kcal"] = row["protein_g"] * 4 + row["carbs_g"] * 4 + row["fat_g"] * 9

    lo, hi = OFFICIAL_BANDS[draft.meal_time]
    if not (lo <= row["kcal"] <= hi):
        problems.append(
            f"kcal {row['kcal']} outside the {draft.meal_time} band [{lo}, {hi}] — "
            "adjust the gram amounts rather than the number"
        )
    min_protein = MIN_PROTEIN_G[draft.meal_time]
    if row["protein_g"] < min_protein:
        problems.append(
            f"protein {row['protein_g']} g below the {draft.meal_time} "
            f"minimum of {min_protein} g"
        )

    for text_field in ("name_en", "name_es", "description_en", "description_es"):
        if not (getattr(draft, text_field) or "").strip():
            problems.append(f"{text_field} is empty")

    bad_regions = set(draft.regions) - set(SUPPORTED_MARKETS)
    if bad_regions:
        problems.append(f"unsupported regions {sorted(bad_regions)}")
    if not draft.regions:
        problems.append("regions is empty — the recipe would reach no market")

    bad_conditions = set(draft.recommended_conditions) - set(SUPPORTED_CONDITIONS)
    if bad_conditions:
        problems.append(
            f"unsupported conditions {sorted(bad_conditions)} — REGLA #0.5.C "
            f"allows only {list(SUPPORTED_CONDITIONS)}"
        )

    # Instructions: derived from the components when the batch omits them, so a
    # recipe can never ship with an empty step list again.
    en = list(draft.instructions_en or [])
    es = list(draft.instructions_es or [])
    if len(en) < MIN_INSTRUCTION_STEPS or len(es) < MIN_INSTRUCTION_STEPS:
        en, es = build_instructions([n for n, _ in draft.components], draft.meal_time)
    row["instructions_en"] = en
    row["instructions_es"] = es

    goals = draft.target_goals or derive_goals(row["kcal"], row["protein_g"], draft.meal_time)
    if not goals:
        problems.append("target_goals is empty — Layer 1 could never select this recipe")
    row["target_goals"] = sorted(set(goals))

    keys = [resolve_key(n) for n, _ in draft.components]
    row["tags"] = sorted(set(draft.tags or derive_tags(
        row["kcal"], row["protein_g"], row["fiber_g"], row["sat_fat_g"],
        row["sugar_g"], row["sodium_mg"], keys)))
    row["allergens"] = derive_allergens(draft.components)

    # Vegan/vegetarian are fail-safe filters: a wrong TRUE serves an animal
    # dish to a vegan. Derived from the ingredients, and a claim the components
    # contradict is rejected outright.
    roles = {classify(k) for k in keys}
    has_animal = "protein_animal" in roles
    has_dairy = "dairy_cold" in roles
    if draft.is_vegan and (has_animal or has_dairy):
        problems.append("is_vegan=True but the components include animal products")
    if draft.is_vegetarian and has_animal:
        problems.append("is_vegetarian=True but the components include meat, fish or egg")
    row["is_vegan"] = draft.is_vegan
    row["is_vegetarian"] = draft.is_vegetarian or draft.is_vegan or not (has_animal or has_dairy)

    if problems:
        raise IngestError(f"{draft.name_en!r}: " + "; ".join(problems))
    return row


async def ingest(conn, draft: RecipeDraft, *, skip_duplicates: bool = True) -> str | None:  # noqa: ANN001
    """Validate, derive and insert. Returns the new id, or None if skipped.

    Components are written BEFORE the nutrition update, because the
    `sync_recipe_aggregates` trigger fires on component writes. Doing it the
    other way round is how several batches had their nutrition zeroed out
    (see migration 0036).
    """
    row = build_row(draft)

    if skip_duplicates:
        existing = await conn.fetchval(
            "SELECT id FROM recipes WHERE lower(name_en) = lower($1)", draft.name_en)
        if existing:
            return None

    recipe_id = await conn.fetchval(
        """
        INSERT INTO recipes (
            name_en, name_translations, description_en, description_translations,
            meal_time, prep_min, tags, allergens, target_goals,
            recommended_conditions, contraindicated_conditions,
            regions, excluded_countries,
            is_vegetarian, is_vegan, pregnancy_safe,
            instructions_en, instructions_translations,
            image_url, source_batch, verified_by
        ) VALUES (
            $1, $2::jsonb, $3, $4::jsonb,
            $5::meal_time_enum, $6, $7::text[], $8::text[]::allergen_enum[],
            $9::text[]::goal_enum[],
            $10::text[], ARRAY[]::text[],
            $11::text[]::char(5)[], $12::text[],
            $13, $14, $15,
            $16, $17::jsonb,
            $18, $19, $20
        ) RETURNING id
        """,
        draft.name_en, json.dumps({"es": draft.name_es}),
        draft.description_en, json.dumps({"es": draft.description_es}),
        draft.meal_time, draft.prep_min, row["tags"], row["allergens"],
        row["target_goals"], list(draft.recommended_conditions),
        list(draft.regions), list(draft.excluded_countries),
        row["is_vegetarian"], row["is_vegan"], draft.pregnancy_safe,
        row["instructions_en"], json.dumps({"es": row["instructions_es"]}),
        draft.image_url, draft.source_batch, draft.verified_by,
    )

    for name, grams in draft.components:
        await conn.execute(
            "INSERT INTO recipe_components (recipe_id, free_text_name, amount_g) "
            "VALUES ($1, $2, $3)", recipe_id, name, float(grams))

    await conn.execute(
        """
        UPDATE recipes SET
            kcal = $1, protein_g = $2, carbs_g = $3, fat_g = $4,
            fiber_g = $5, sugar_g = $6, added_sugar_g = $7, sodium_mg = $8,
            sat_fat_g = $9, potassium_mg = $10, phosphorus_mg = $11,
            calcium_mg = $12, iron_mg = $13, folate_ug = $14
         WHERE id = $15
        """,
        row["kcal"], row["protein_g"], row["carbs_g"], row["fat_g"],
        row["fiber_g"], row["sugar_g"], row["added_sugar_g"], row["sodium_mg"],
        row["sat_fat_g"], row["potassium_mg"], row["phosphorus_mg"],
        row["calcium_mg"], row["iron_mg"], row["folate_ug"], recipe_id,
    )
    return str(recipe_id)
