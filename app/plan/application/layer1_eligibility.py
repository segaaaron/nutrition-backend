"""Layer 1 — Eligibility filter (deterministic SQL, no LLM).

Filters the recipe catalog down to the candidate set for a given user × meal
slot. **Hard** rules (no soft fallback), except region (see 1):

  1. Region overlap: `recipes.regions && ARRAY[user.region]` (ADR-0008).
     SOFT since 2026-06-10 (owner decision): if the user's market yields zero
     candidates after all safety filters, the region clause is dropped and
     the query retries against the whole catalog (warning logged). Safety
     filters (2-4) are never relaxed; Layer3 cultural_fit still prefers
     same-region recipes in ranking.
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
  4. Condition-specific gates (per spec §6 / ADR-0001). In-scope conditions
     only (owner decision 2026-07-09 — NOVA is a general nutrition app, not a
     medical tool):
       fatty_liver → added_sugar_g ≤ 8 AND sat_fat_g ≤ 5 AND fiber_g ≥ 3
       pregnancy   → pregnancy_safe = TRUE
       lactation   → pregnancy_safe = TRUE
  5. Meal-time match.

Budget: <50 ms (single round-trip indexed query, GIN-backed array ops).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

_log = get_logger("plan.layer1")

# FALCPA / EU 1169 declared tree nuts. Lowercase ASCII-stripped match patterns
# applied via regex over component free_text_name and joined food name.
_TREE_NUT_PATTERN = (
    r"\m(almond|almendra|walnut|nuez|cashew|maranon|maranón|maraño|maranõ|"
    r"pistachio|pistacho|pecan|pacana|hazelnut|avellana|macadamia|"
    r"brazil\s*nut|nuez\s*de\s*brasil|pine\s*nut|pinon|piñon|chestnut|castana|castaña)\M"
)

# CLAUDE.md §REGLA PAÍSES SIN MAR — landlocked countries in current markets (LATAM).
# Secondary defense-in-depth filter (allergen/tag blacklist) scoped to active markets.
# Primary filter is the `excluded_countries` column — generic for any ISO code.
# Frozenset: immutable, O(1) lookup, GC-free — created once at import.
_LANDLOCKED_COUNTRIES: frozenset[str] = frozenset({"BO", "PY"})


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
        dietary_pattern = (prof.get("dietary_pattern") or "").lower().strip()
        disliked: list[str] = [
            d.strip() for d in (prof.get("disliked_ingredients") or []) if d and d.strip()
        ]

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
        # Include the user's ISO-2 country code so v3 catalog recipes
        # (tagged with lowercase country like "pe", "mx") are eligible
        # alongside old-catalog recipes (tagged with market strings like
        # "latam"). The OR inside `&&` operator handles both transparently.
        allowed_tags: list[str] = list({region, country.lower(), "world"} - {""}) if country else [region, "world"]

        where: list[str] = [
            "r.regions && CAST(:regions AS char(5)[])",
            "r.meal_time = :meal_time",
            # Quarantine (migration 0031): recipes whose stored macros are known
            # to be wrong — today the `meals_v4` batch, whose duplicated
            # component rows inflated kcal/protein past the slot band. Lives in
            # `where`, so it survives the region and meal-time fallbacks below:
            # a recipe with bad nutrition is never the lesser evil.
            "r.quarantined_at IS NULL",
        ]
        params: dict[str, object] = {
            "regions": allowed_tags,
            "meal_time": meal_time,
        }

        # Dietary pattern hard-exclude (2026-06-16). The onboarding form
        # collects vegan/vegetarian and promises on-screen "NOVA excluirá los
        # alimentos que no comes". Vegan/vegetarian users must NEVER be served
        # an animal dish. Flags are denormalised (is_vegan / is_vegetarian),
        # backfilled from ingredients (scripts/backfill_diet_flags.py). NULL =
        # unclassified ⇒ EXCLUDED for these users (fail-safe): serving a
        # possibly-animal dish to a vegan is the unrecoverable error. `IS TRUE`
        # is NULL-safe (NULL → excluded). Survives the region/meal-time
        # fallbacks below because it lives in `where` — a safety filter, never
        # relaxed. Omnivore (and any unknown value) → no extra filter.
        _KNOWN_DIETARY_PATTERNS = {"vegan", "vegetarian", "pescatarian", "omnivore", ""}
        if dietary_pattern not in _KNOWN_DIETARY_PATTERNS:
            _log.warning(
                "layer1.unknown_dietary_pattern",
                dietary_pattern=dietary_pattern,
                user_id=str(user_id),
            )
        if dietary_pattern == "vegan":
            where.append("r.is_vegan IS TRUE")
        elif dietary_pattern == "vegetarian":
            where.append("r.is_vegetarian IS TRUE")
        elif dietary_pattern == "pescatarian":
            # Pescatarian eats fish/seafood but no land-animal meat.
            # `IS FALSE` is NULL-safe: NULL IS FALSE → FALSE → excluded.
            # `IS NOT TRUE` would include NULL (NULL IS NOT TRUE → TRUE) — wrong.
            where.append("r.contains_meat IS FALSE")

        # Per-recipe country exclusion list (migration 0025, ADR §REGLA PAÍSES
        # SIN MAR). Applied for EVERY user with a known country. The column
        # defaults to '{}' for all existing recipes, so NOT (:country =
        # ANY('{}')) always evaluates TRUE — no impact on current catalog.
        # This is a HARD safety filter: never dropped in any fallback branch.
        if country:
            where.append("NOT (:country = ANY(r.excluded_countries))")
            params["country"] = country

        if country in _LANDLOCKED_COUNTRIES:
            where.append(
                "NOT (r.allergens && ARRAY['shellfish','molluscs']::allergen_enum[])"
            )
            where.append(
                "NOT (r.tags && ARRAY['shellfish','molluscs','camarones','langosta','cangrejo',"
                "'mariscos','sea_fish','pescado_mar']::text[])"
            )
            _log.info("layer1.landlocked_filter_applied", country=country)

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

            # ConditionGate Strategy dispatch (H2). All condition-specific SQL
            # fragments come from the registry — no inline if-chains needed.
            from app.plan.domain.condition_gates import gates_for

            for cond in conditions:
                for gate in gates_for(cond):
                    g_sql, g_params = gate.contribute_sql()
                    where.append(g_sql)
                    params.update(g_params)

        # Disliked-ingredient taste exclusion (2026-07-20). Free-text foods the
        # user marked "no como esto". A recipe is dropped if ANY component name
        # matches ANY disliked term (case-insensitive substring). This is a
        # PREFERENCE, not a safety filter: it is `disliked_clause` and is the
        # FIRST clause relaxed in the fallback below, so a picky profile can
        # never abort plan generation — safety filters stay hard.
        disliked_clause: str | None = None
        if disliked:
            disliked_clause = (
                "NOT EXISTS ("
                " SELECT 1 FROM recipe_components rc"
                " WHERE rc.recipe_id = r.id"
                " AND lower(coalesce(rc.free_text_name, '')) ILIKE ANY(:disliked_patterns)"
                ")"
            )
            where.append(disliked_clause)
            params["disliked_patterns"] = [f"%{d.lower()}%" for d in disliked]

        # S608 noqa: `where` is assembled exclusively from literal SQL
        # fragments authored in this function or returned by registered
        # ConditionGate strategies. User-controlled values are bound via
        # :params. No injection vector.
        # ORDER BY r.id: deterministic candidate order so seeded plan
        # generation is reproducible (heap order varies across runs).
        sql = f"""
            SELECT r.id FROM recipes r
             WHERE {' AND '.join(where)}
             ORDER BY r.id
        """  # noqa: S608
        res = await self.session.execute(text(sql), params)
        ids = [row[0] for row in res.all()]
        if ids:
            return ids

        # Disliked-ingredient fallback (2026-07-20): a taste preference is NOT
        # safety. If excluding disliked foods empties the pool, relax it first
        # (serve a disliked-but-safe meal rather than abort). Reassigning
        # `where` here means the region/meal-time fallbacks below also run
        # without the disliked clause. Safety filters remain in place.
        if disliked_clause is not None and disliked_clause in where:
            where = [w for w in where if w != disliked_clause]
            sql_no_dislike = f"""
                SELECT r.id FROM recipes r
                 WHERE {' AND '.join(where)}
                 ORDER BY r.id
            """  # noqa: S608
            res = await self.session.execute(text(sql_no_dislike), params)
            ids = [row[0] for row in res.all()]
            if ids:
                _log.warning(
                    "layer1.disliked_fallback_used",
                    n_disliked=len(disliked),
                    meal_time=meal_time,
                    n_candidates=len(ids),
                )
                return ids

        # Region fallback (owner decision 2026-06-10): region is a cultural
        # preference, NOT a safety filter. If the user's market has zero
        # eligible recipes after allergen + condition gates, retry across the
        # whole catalog rather than failing plan generation outright. Safety
        # filters (allergens, condition gates) are NEVER relaxed — only the
        # region overlap clause is dropped. Layer3 cultural_fit still ranks
        # same-region recipes first, so local dishes win whenever they exist.
        # cultural_fit now gives 0.0 to foreign recipes so even in global mode
        # the ranking keeps cultural relevance (2026-06-18 fix).
        region_clause = "r.regions && CAST(:regions AS char(5)[])"
        meal_time_clause = "r.meal_time = :meal_time"
        where_no_region = [w for w in where if w != region_clause]
        if region_clause in where:
            sql_global = f"""
                SELECT r.id FROM recipes r
                 WHERE {' AND '.join(where_no_region)}
                 ORDER BY r.id
            """  # noqa: S608
            res = await self.session.execute(text(sql_global), params)
            ids = [row[0] for row in res.all()]
            if ids:
                _log.warning(
                    "layer1.region_fallback_used",
                    region=region,
                    meal_time=meal_time,
                    n_global=len(ids),
                )
                return ids

        # Cross-meal-time fallback (2026-06-11 root-cause hardening for
        # `plan_generation_yielded_no_meals`). When the catalog has zero
        # recipes tagged for the requested meal_time but DOES have safe
        # recipes for other meal_times under the same allergen + condition
        # constraints, accept those instead. A recipe whose `meal_time`
        # column says "lunch" is still nutritionally appropriate at dinner;
        # the user-facing meal slot is purely a label. Safety filters
        # (allergens, condition gates) remain hard. Without this fallback,
        # a single empty meal_time bucket for a user's allergen profile
        # crashes the entire 7-day pipeline.
        where_no_meal = [w for w in where_no_region if w != meal_time_clause]
        sql_any_meal = f"""
            SELECT r.id FROM recipes r
             WHERE {' AND '.join(where_no_meal)}
             ORDER BY r.id
        """  # noqa: S608
        res = await self.session.execute(text(sql_any_meal), params)
        ids = [row[0] for row in res.all()]
        if ids:
            _log.warning(
                "layer1.cross_meal_fallback_used",
                region=region,
                meal_time=meal_time,
                n_global=len(ids),
            )
        return ids
