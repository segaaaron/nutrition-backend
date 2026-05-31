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
   with exactly the 25 canonical values listed in Appendix A below, plus a
   CHECK constraint via a domain table
   `condition_vocabulary(code text pk, icd10_category text, active bool)`.
   Application code rejects writes of any code not present-and-active.
   Adding or removing a value requires an **ADR amendment** (not a code change
   alone) plus a backfill / deprecation plan; see Governance below.
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

## Appendix A — Canonical conditions (Spanish StrEnum, 25 values)

Clinical priority list curated by `nova-clinical-nutrition-generator` and
`nova-qa-elite`. Spanish snake_case identifiers match the DB enum convention
(§21 of the design spec); ICD-10 categories are informational and used by the
admin tooling to group filters.

| Code (es) | ICD-10 category | Notes |
|---|---|---|
| `diabetes_t1` | E10 | insulin-dependent |
| `diabetes_t2` | E11 | non-insulin-dependent |
| `hipertension` | I10 | essential hypertension |
| `dislipidemia` | E78 | incl. mixed hyperlipidaemia |
| `hipercolesterolemia` | E78.0 | LDL-driven filters |
| `hipotiroidismo` | E03 | iodine/selenium considerations |
| `hipertiroidismo` | E05 | caffeine/iodine guidance |
| `sii` | K58 | irritable bowel — FODMAP filter |
| `eii` | K50–K51 | Crohn / UC |
| `celiaca` | K90.0 | hard-exclude gluten (also via allergen) |
| `intolerancia_lactosa` | E73 | distinct from dairy allergy |
| `obesidad` | E66 | BMI ≥ 30 derived |
| `sobrepeso` | E66.3 | 25 ≤ BMI < 30 |
| `embarazo` | Z33 | pregnancy — folate / iron uplift |
| `lactancia` | Z39.1 | lactation — kcal/protein uplift |
| `atletismo` | Z02.5 | athletic load — performance fueling |
| `ercc` | N18 | chronic kidney disease — K/Na/protein limits |
| `cardiopatia` | I25 | ischaemic heart disease |
| `higado_graso` | K76.0 | NAFLD — sat-fat / fructose limits |
| `anemia_ferropenica` | D50 | iron-rich + cofactor pairing |
| `sop` | E28.2 | polycystic ovary — insulin-resistance pattern |
| `gota` | M10 | purine-restrict |
| `deficit_vitamina_d` | E55 | sun + supplementation context |
| `insomnio_cronico` | G47.0 | caffeine / late-meal guidance |
| `depresion_leve` | F32.0 | omega-3 / Mediterranean pattern |

**Governance rule.** Additions require a new ADR (amendment to ADR-0001),
nutritionist sign-off, ICD-10 mapping, plan-filtering test scenarios, and a
backfill plan. Removals are not permitted — only `active=false` deprecation
to preserve historical plan filters.

## References

- FALCPA 2023 (Food Allergy Safety, Treatment, Education, and Research Act).
- Spec §6, §7, §20, §21.
- Failing tests gated by this ADR:
  `tests/data/test_catalog_ingest.py::test_unknown_allergen_rejects_record`,
  `tests/data/test_catalog_taxonomy.py::test_allergen_and_condition_vocabularies_are_disjoint`,
  `tests/data/test_catalog_taxonomy.py::test_conditions_are_in_canonical_enum`.
