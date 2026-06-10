"""Layer 1 — Eligibility filter (deterministic SQL, no LLM).

Filters the recipe catalog down to the candidate set for a given user × meal
slot. **Hard** rules (no soft fallback):

  1. Region overlap: `recipes.regions && ARRAY[user.region]` (ADR-0008).
  2. Allergen hard-exclude: `NOT (recipes.allergens && user.allergies)` —
     never returns a recipe whose denormalised allergens overlap the user's
     allergies. Enforced through the closed `allergen_enum` (ADR-0001).
     2b. Tree-nut defensive ingredient scan (FALCPA / EU 1169 / anaphylaxis):
         when user allergies includes `tree_nuts`, additionally exclude any
         recipe whose components reference a nut by name even if the
         denormalised allergens array is missing the tag. Catalog audit
         (2026-06-01) found 37 such mistagged recipes.
  3. Contraindicated conditions: any recipe listing a user's condition in
     `contraindicated_conditions` is dropped.
  4. Condition-specific gates (per spec §6 / ADR-0001):
       diabetes_t2          → sugar_g/portion ≤ 15
       hypertension         → sodium_mg/portion ≤ 600
       ckd                  → protein_g/portion ≤ weight_kg * 0.8 / 3
       hypercholesterolemia → sat_fat_g/portion ≤ 5
       gout                 → no purine-heavy tag (organ_meat, shellfish)
  5. Meal-time match.

Budget: <50 ms (single round-trip indexed query, GIN-backed array ops).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# FALCPA / EU 1169 declared tree nuts. Lowercase ASCII-stripped match patterns
# applied via regex over component free_text_name and joined food name.
_TREE_NUT_PATTERN = (
    r"\m(almond|almendra|walnut|nuez|cashew|maranon|maranón|maraño|maranõ|"
    r"pistachio|pistacho|pecan|pacana|hazelnut|avellana|macadamia|"
    r"brazil\s*nut|nuez\s*de\s*brasil|pine\s*nut|pinon|piñon|chestnut|castana|castaña)\M"
)


class _ProfileReader(Protocol):
    async def get_eligibility_profile(
        self, user_id: UUID
    ) -> dict | None: ...  # {region, allergies[], conditions[], weight_kg}


@dataclass(slots=True)
class Layer1Eligibility:
    session: AsyncSession
    profile_reader: _ProfileReader

    async def __call__(self, *, user_id: UUID, meal_time: str) -> list[UUID]:
        prof = await self.profile_reader.get_eligibility_profile(user_id)
        if prof is None:
            return []

        country = (prof.get("country") or "").upper().strip()
        allergies: list[str] = prof.get("allergies") or []
        conditions: list[str] = prof.get("conditions") or []
        weight_kg: Decimal | None = prof.get("weight_kg")

        # Region-based filtering (post-2026-06-09 fix).
        #
        # HISTORICAL DECISION (2026-06-07): originally intended to admit
        # ``world`` + ISO country code tags for strict cultural separation.
        # That required the catalog to be re-tagged per-country (`PE`, `MX`,
        # etc.) plus a `world` marker. The retag script
        # (`scripts/retag_catalog_by_country.py`) was prepared but never run
        # against prod — catalog still uses MARKETS (`us`, `latam`, `eu`,
        # `uk`, `ca`) per the original ADR-0008 model.
        #
        # CURRENT BEHAVIOR: use the pre-computed ``profile.region``
        # (country_to_region mapping at onboarding-save time) so the eligibility
        # query matches the actual catalog tagging. ``country`` is preserved
        # in the profile and still drives Layer3 cultural_fit scoring (which
        # operates on the recipe.regions array as a fuzzy match).
        region = (prof.get("region") or "us").lower().strip()
        allowed_tags: list[str] = [region]

        where: list[str] = [
            "r.regions && CAST(:regions AS char(5)[])",
            "r.meal_time = :meal_time",
        ]
        params: dict[str, object] = {
            "regions": allowed_tags,
            "meal_time": meal_time,
        }

        if allergies:
            # Defensive: cast both sides to text so we never trip enum-vs-text
            # operator-resolution issues in mixed contexts.
            where.append("NOT (CAST(r.allergens AS text[]) && CAST(:allergies AS text[]))")
            params["allergies"] = allergies

            if "tree_nuts" in allergies:
                where.append(
                    "NOT EXISTS ("
                    " SELECT 1 FROM recipe_components rc"
                    " LEFT JOIN foods f ON f.id = rc.food_id"
                    " WHERE rc.recipe_id = r.id"
                    " AND ("
                    "   lower(coalesce(rc.free_text_name,'')) ~* :nut_pattern"
                    "   OR lower(coalesce(f.name_en,'')) ~* :nut_pattern"
                    " )"
                    ")"
                )
                params["nut_pattern"] = _TREE_NUT_PATTERN

        if conditions:
            where.append("NOT (r.contraindicated_conditions && CAST(:conditions AS text[]))")
            params["conditions"] = conditions

            # ----------------------------------------------------------------
            # CRITICAL conditions — FAIL-CLOSED on missing data (R6, 2026-06-03).
            #
            # Policy: for safety-critical filters, a NULL column means
            # the catalog row is INCOMPLETE, not safe. We exclude it rather
            # than include it. This biases recommendations toward recipes with
            # fully audited macros; catalog backfill keeps the candidate pool
            # healthy (see `scripts/catalog_completeness_audit.py`).
            #
            # Trade-off: until backfill is complete, users with these
            # conditions see a narrower catalogue. Acceptable: false negatives
            # (missing safe recipe) are recoverable; false positives (unsafe
            # recipe served to at-risk user) are not.
            # ----------------------------------------------------------------
            if "diabetes_t2" in conditions:
                # Source: ADA 2024 Standards of Care — added sugars ≤10% kcal
                # ⇒ ≈15 g/meal at ~2000 kcal across 4 occasions.
                where.append("(r.sugar_g IS NOT NULL AND r.sugar_g <= 15)")
            if "hypertension" in conditions:
                # Source: 2017 ACC/AHA + WHO 2023 — Na <2000 mg/day ⇒
                # ≤600 mg/meal at 3 meals with snack margin.
                where.append("(r.sodium_mg IS NOT NULL AND r.sodium_mg <= 600)")
            if "hypercholesterolemia" in conditions:
                # Source: 2018 AHA/ACC Cholesterol Guideline (Circulation
                # 139:e1082) — sat fat <6% kcal ⇒ ≈5 g/meal at 2000 kcal/3
                # meals.
                where.append("(r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= 5)")
            if "ckd" in conditions and weight_kg is not None:
                # Source: KDOQI 2020 Nutrition in CKD — 0.8 g protein/kg/day
                # spread across 3 meals as the non-dialysis-dependent
                # conservative target (real recommendation is 0.55-0.60
                # g/kg/day for stages 3-5 without diabetes).
                ckd_cap = max(1, int(float(weight_kg) * 0.8 / 3))
                where.append("(r.protein_g IS NOT NULL AND r.protein_g <= :ckd_protein_cap)")
                params["ckd_protein_cap"] = ckd_cap
            if "gout" in conditions:
                where.append("NOT (r.tags && ARRAY['organ_meat','shellfish']::text[])")
            # ConditionGate Strategy dispatch (H2). Registered gates live in
            # app/plan/domain/condition_gates. Layer 1 dispatches ALL registered
            # gates for each declared user condition, composing their SQL
            # fragments via AND. Adding a new condition = new Strategy class +
            # `register_gate(...)` call — Layer 1 needs no edit.
            #
            # Currently registered: lactation, pregnancy, diabetes_t2, ckd,
            # hypertension, celiac. Defensive COALESCE on un-backfilled
            # micronutrient columns (safety > variety).
            from app.plan.domain.condition_gates import gates_for

            for cond in conditions:
                for gate in gates_for(cond):
                    g_sql, g_params = gate.contribute_sql()
                    where.append(g_sql)
                    params.update(g_params)

        # S608 noqa: `where` is assembled exclusively from literal SQL
        # fragments authored in this function or returned by registered
        # ConditionGate strategies. User-controlled values are bound via
        # :params. No injection vector.
        sql = f"""
            SELECT r.id FROM recipes r
             WHERE {' AND '.join(where)}
        """  # noqa: S608
        res = await self.session.execute(text(sql), params)
        return [row[0] for row in res.all()]
