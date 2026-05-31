# ADR-0008 — Multi-region recipe catalog (`regions[]` + per-region allergen subset)

- Status: Accepted
- Date: 2026-05-31
- Deciders: nova-nutrition-backend-architect, nova-clinical-nutrition-generator,
  nova-qa-elite, product owner
- Related: ADR-0001 (allergen vocabulary — 14-item superset), ADR-0007 (i18n)

## Context

Round-3 product decision: launch v0.1 in **USA + LatAm simultaneously**, with
EU as a near-term target (payments rails Stripe US/CA/EU + Mercado Pago LatAm
are in scope). Three concrete differences across regions affect catalog
correctness:

1. **Allergen disclosure law differs**.
   - US FALCPA 2023: top-9 (`dairy, gluten, tree_nuts, peanuts, shellfish,
     fish, egg, soy, sesame`).
   - Canada CFIA: top-9 + `mustard`, `sulphites` (11 total).
   - EU 1169/2011 Annex II: 14 total (US-9 + `celery`, `mustard`, `lupin`,
     `sulphites`, `molluscs`).
   - UK: aligned with EU 14.
2. **Cultural fit**. A `causa peruana` snack is a hit in LatAm and an
   unknown in Germany; a `pretzel & mustard` snack is a hit in DE and a
   miss in PE. Plan generation has to respect this without manually curating
   per-country catalogs.
3. **Ingredient availability**. Some LatAm ingredients (`lúcuma`,
   `chirimoya`) are not retail in the US/EU; some EU ingredients (`speck`,
   `Quark`) are not retail in LatAm. Recipes whose ingredients fail the
   regional availability check must be excluded from plan generation for
   users in those regions.

## Decision

1. **`recipes.regions char(5)[]` is mandatory** (`NOT NULL DEFAULT '{}'`).
   Empty array means "no region" → recipe is invisible to plan generation.
   Recipes intended for global use are tagged with all five region codes.

2. **Region codes (initial set)**: `us`, `ca`, `eu`, `uk`, `latam`. The
   `regions` table holds metadata (allergen_set, countries, default_locale)
   and is seeded by migration 0001.

3. **Allergen subset per region**.
   - `us`: 9 (FALCPA top-9).
   - `ca`: 11 (US-9 + `mustard`, `sulphites`).
   - `eu`, `uk`: 14 (full superset).
   - `latam`: 9 (FALCPA top-9 — same as US for v0.1; revisit if a LatAm
     country mandates a wider disclosure list).

   Stored as `regions.allergen_set allergen_enum[]`. Drives:
   - The allergen-checkbox set in the UI (US users do not see `celery` etc.
     unless they opt into "show EU-extended allergens").
   - Catalog ingest gate 5 (allergen completeness check uses the user's
     effective region; cross-region recipes must declare allergens from the
     full 14-superset to remain valid across all tagged regions).

4. **Plan generation hard-filter** (spec §9.5 step 2):
   ```sql
   WHERE recipes.regions && ARRAY[$user_region]::char(5)[]
   ```
   plus the allergen exclusion. The `gin` index on `recipes.regions`
   handles this efficiently at catalog size up to ~500 k rows.

5. **Cross-catalog dedup**. A normalised-name Levenshtein ≤ 2 across
   different `source_catalog` values is **flagged for human review** (not
   auto-merged) because the same Spanish-language name in a `latam` batch
   and a `us` batch may genuinely refer to two different recipes (e.g. a
   Mexican vs Peruvian `ceviche`). Resolution is recorded in a manual
   `recipe_region_aliases` follow-up table (out of scope for v0.1).

6. **Cultural fallback substitutions**. When a recipe matches the user's
   region but contains a regionally-unavailable ingredient, the
   composition-pattern engine attempts substitution via
   `ingredient_substitutions(from_ingredient, to_ingredient, region)` (table
   added in a follow-up migration). If no substitution exists, the recipe
   is dropped from the candidate set for that user.

7. **Default region on profile creation**. Derived from `country` via
   `regions.countries`. If `country` is null/unknown the default is `us`
   (most conservative allergen-disclosure regime).

## Governance

- Adding a region: new ADR + migration + UI strings in every locale +
  curated batch of ≥ 100 region-tagged recipes per meal_time + nutritionist
  sign-off for any region-specific allergen subset deviation.
- Changing a region's `allergen_set`: must follow ADR-0001 governance (FDA
  / Codex / regulatory citation) and a backfill plan for every recipe
  tagged with that region.
- Removing a region: deprecation only — set `regions.active=false`
  (column to be added when first removal is needed); recipes keep their
  tags for historical plan filters.

## Consequences

- The current seed catalog (2000 LatAm-Spanish recipes) is tagged
  `regions: ['latam']` by the `audit_catalog.py --apply-fixes` step. A
  follow-up curation pass (data-ops) re-tags universally-applicable recipes
  with additional regions.
- Plan generation latency picks up one extra `&&` filter; impact measured
  in `tests/perf/test_plan_generation.py` is negligible (gin overlap on a
  5-element array).
- The UI must read the user's `region.allergen_set` to render the allergen
  selection screen; existing onboarding screens that hard-code 9 allergens
  must be parameterised.

## Trade-offs considered

- **Per-country tagging instead of region**: rejected — 200+ ISO-3166
  codes explode the array size and the curation cost without buying real
  fidelity (a Mexican recipe is rarely "available in MX but not PE").
- **Boolean `is_global` flag**: rejected — does not encode allergen-subset
  differences, which are the legally-binding part.
- **Separate `recipes_<region>` tables**: rejected — denormalises the
  catalog, breaks cross-region semantic search via pgvector, and forces a
  schema change for every new region.

## References

- Spec §2 (decisions), §7 (regions table + recipes.regions), §9.5 (plan
  generation hard-filter), §21 (region-aware allergen UI).
- FALCPA 2023, EU Regulation 1169/2011 Annex II, CFIA priority allergens.
- ADR-0001 (closed allergen vocabulary, 14-item superset).
- ADR-0007 (i18n — `regions.default_locale`).
