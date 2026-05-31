# ADR-0001 — Closed vocabularies for allergens and medical conditions

- Status: Accepted
- Date: 2026-05-30
- Deciders: nova-nutrition-backend-architect, nova-qa-elite
- Supersedes: n/a

## Context

Pre-implementation QA review (`docs/qa/2026-05-30-pre-implementation-review.md`,
findings #1, #3, #4) showed three structural defects in the catalog data:

1. The allergen field accepts arbitrary strings; the seed data already contains
   `sesame` (22 records) and `mustard` (1 record) outside the agent-declared
   set `{dairy, gluten, tree_nuts, peanuts, shellfish, fish, egg, soy}`. Any
   `WHERE allergen = ANY($1)` filter silently drops unknown values, producing
   false-negative exclusions on the **safety pillar** of the product.
2. Allergen tokens (`egg`, `shellfish`, `fish`) leak into the
   `recommendedForConditions` / `contraindicatedConditions` arrays in 26 records.
3. The condition vocabulary has 62 distinct labels with semantic duplicates
   (`peanut_allergy` vs `peanuts_allergy`, `build_muscle` / `muscle_building` /
   `muscle_hypertrophy`, invented entries like `liver_detox`).

Without a closed enum at the schema layer, condition-based plan filtering and
allergen hard-exclude are not enforceable.

## Decision

1. **Allergen vocabulary is a Postgres `ENUM`** (`allergen_enum`) with exactly
   nine values, matching the FALCPA 2023 top-9 US allergen list:
   `dairy, gluten, tree_nuts, peanuts, shellfish, fish, egg, soy, sesame`.
2. **Condition vocabulary is a Python `StrEnum`** in `app/recipes/domain/conditions.py`
   (≤25 values) and a CHECK constraint via a domain table
   `condition_vocabulary(code text pk, icd10_category text, active bool)`.
   Application code rejects writes of any code not present-and-active.
3. **Disjointness invariant**: `allergens ∩ conditions == ∅` enforced at ingest
   (gate #4 in §20 of the spec) and as a domain assertion before persistence.
4. **Sesame is included** in the allergen enum because it is a US top-9 allergen
   and already appears in 22 catalog records; omitting it would force a near-term
   migration.

## Governance

- New allergen values: require an FDA / Codex Alimentarius citation **and** a
  schema migration **and** a UI string in every supported locale **and** a backfill
  plan for existing recipes. Reviewed by qa-elite + clinical-nutrition-generator.
- New condition values: require ICD-10 category mapping **and** test scenarios
  for plan filtering (positive and negative cases). Reviewed by the same pair.
- Removals: never — deprecation only (`active=false`), to preserve historical
  recipe filters and avoid plan-regen contract breakage.

## Consequences

- All catalog rows with `mustard` are rejected at ingest until a migration adds
  it (currently 1 row, low blast radius).
- Existing 26 catalog records with allergen tokens in `conditions` fields are
  rejected by gate #4; they must be cleaned manually before re-ingest.
- ICD-10 alignment becomes feasible in a future ADR without a vocabulary rewrite.

## References

- FALCPA 2023 (Food Allergy Safety, Treatment, Education, and Research Act).
- Spec §6, §7, §20, §21.
- Failing tests gated by this ADR:
  `tests/data/test_catalog_ingest.py::test_unknown_allergen_rejects_record`,
  `tests/data/test_catalog_taxonomy.py::test_allergen_and_condition_vocabularies_are_disjoint`,
  `tests/data/test_catalog_taxonomy.py::test_conditions_are_in_canonical_enum`.
