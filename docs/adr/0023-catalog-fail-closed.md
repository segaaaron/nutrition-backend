# ADR-0023 — Catalog fail-closed for critical condition columns

- Status: Accepted
- Date: 2026-06-03
- Deciders: Owner (Miguel Saravia), nova-nutrition-backend-architect, nova-qa-elite, nova-clinical-nutrition-generator
- Supersedes: n/a
- Tags: nutrition-safety, catalog, plan, layer-1, fail-closed

## Context

Layer 1 eligibility SQL filters recipes for users with critical conditions (diabetes_t2, hypertension, hypercholesterolaemia, CKD, lactation, pregnancy) using catalog columns such as `sugar_g`, `sodium_mg`, `sat_fat_g`, `protein_g`, `potassium_mg`.

Pre-Sprint 2 the predicate was:

```sql
(col IS NULL OR col <= :threshold)
```

This biases toward **include** on NULL. Rationale at the time: maximise candidate set on incomplete catalog. The hidden cost: a CKD user receives a high-potassium recipe whose `potassium_mg` is NULL — the user has no way to know the column was missing, the algorithm produced a unsafe recommendation.

Sprint 2 R6 flagged the asymmetry: a false-negative (excluding a safe recipe) is recoverable on the next catalog backfill; a false-positive (serving an unsafe recipe to a nutrition-condition user) is not.

## Decision

For critical condition columns the predicate becomes:

```sql
(col IS NOT NULL AND col <= :threshold)
```

NULL → exclude. The candidate set shrinks proportionally to NULL density per column, but every recipe returned has a verified value below the nutrition threshold.

### Critical column set per condition

| Condition | Columns requiring NOT NULL + threshold |
|-----------|-----------------------------------------|
| `diabetes_t2` | `sugar_g`, `gi` (glycaemic index), `fiber_g` (lower bound, NOT NULL AND ≥ threshold) |
| `hypertension` | `sodium_mg`, `potassium_mg` (lower bound) |
| `hypercholesterolaemia` | `sat_fat_g`, `cholesterol_mg`, `fiber_g` (lower bound) |
| `ckd` | `potassium_mg`, `phosphorus_mg`, `protein_g` (upper bound per ADR-0019) |
| `lactation` | `iodine_µg` (lower), `calcium_mg` (lower) per ADR-0016 |
| `pregnancy` | `folate_µg` (lower), `iron_mg` (lower) per ADR-0020 |

Non-critical columns (e.g. `prep_minutes`, `cuisine`) retain permissive NULL handling.

### Catalog completeness boot-guard

`scripts/catalog_completeness_audit.py` runs at container start (entrypoint) and on demand:

- For each `(region, critical_column)` pair compute NULL density across active recipes.
- **>10 % NULL** on any critical column → exit non-zero. Container refuses to boot. Owner alerted.
- **>5 % NULL** → log soft warning, boot succeeds.
- **≤5 % NULL** → silent pass.

Boot-guard is the safety net that makes the SQL change politically tractable: NULL columns must be backfilled, not hidden.

## Consequences

### Positive
- A NULL `sodium_mg` recipe cannot reach a hypertension user. Single biggest nutrition-safety improvement of Sprint 2.
- Backfill pressure becomes visible (boot fails on >10 % NULL), forcing catalog discipline.
- Soft warning at 5 % gives early signal before hard failure.

### Negative
- Candidate set shrinks. Plan generator may fall back to `geriatric_requires_specialist_review` style escape signals more often during catalog ramp-up.
- Boot-guard requires DB connectivity at startup; offline-init is no longer possible. Acceptable for VPS deploy.
- Backfill cost: nova-clinical-nutrition-generator and manual review required for any column dipping above threshold.

### Risk accepted
- Boot-guard threshold (10 %) is judgement-based. Tunable per ADR amendment if backfill velocity proves slower than expected. Currently main-region catalogs (MX, AR, CL, PE, CO) sit at <3 % NULL on all critical columns.

## Mitigation roadmap

1. nova-clinical-nutrition-generator scheduled to close >5 % NULL columns within 30 days of any warning.
2. Catalog ingest pipeline (`scripts/audit_catalog.py`) extended in Sprint 3 to reject ingest rows missing critical columns for their region.
3. PROJECT_STATE.md tracks current NULL density per critical column per region.

## References

- Code: `app/plan/application/layer1_eligibility.py`, `app/plan/domain/condition_gates/{ckd,diabetes_t2,hypertension,lactation,pregnancy}.py`, `scripts/catalog_completeness_audit.py`, `docker/entrypoint.sh`
- Tests: `tests/unit/plan/test_allergen_invariant.py`, `tests/unit/plan/test_multi_condition.py`
- Related: ADR-0016 (lactation lift), ADR-0018 (diabetes_t2 lift), ADR-0019 (CKD lift), ADR-0020 (pregnancy lift), ADR-0014 (allergen freetext refuse policy)
- PROJECT_STATE.md §catalog-completeness
