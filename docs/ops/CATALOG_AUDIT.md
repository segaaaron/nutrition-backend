# Catalog Completeness Audit — Runbook

**Status:** active since 2026-06-03
**Owner:** backend / data
**Trigger:** R6 fail-closed policy (`docs/handoff/` + Layer 1 inline comments)

---

## 1. Context

R6 (2026-06-03) flipped Layer 1 eligibility from **bias-include** (`col IS NULL OR col <= threshold`) to **fail-closed** (`col IS NOT NULL AND col <= threshold`) for nutrition-safety-critical columns.

This means a recipe with `sodium_mg = NULL` is **excluded** from candidate sets for hypertensive users instead of being treated as safe. Safer for the user, costly for catalogue coverage if the data is incomplete.

The audit script measures that cost and tells the operator when to backfill.

---

## 2. Critical columns audited

| Column          | Drives                                          |
|-----------------|-------------------------------------------------|
| `sugar_g`       | diabetes_t2 Layer 1 + condition_gate            |
| `sodium_mg`     | hypertension + ckd                              |
| `sat_fat_g`     | hypercholesterolemia                            |
| `potassium_mg`  | ckd                                             |
| `protein_g`     | ckd Layer 1 protein cap                         |
| `fiber_g`       | diabetes_t2 fiber minimum                       |

If any of these exceeds the configured NULL ratio threshold, recipes for affected users will be silently filtered out.

---

## 3. How to run

```bash
make catalog-audit                                                   # default soft threshold 5%
.venv/bin/python -m scripts.catalog_completeness_audit --threshold 0.10
.venv/bin/python -m scripts.catalog_completeness_audit --json
.venv/bin/python -m scripts.catalog_completeness_audit --boot-guard  # only fails on hard breach
```

Exit codes:

| Code | Meaning                                                              |
|------|----------------------------------------------------------------------|
| 0    | All critical columns within threshold                                |
| 1    | At least one column exceeds **soft** threshold (5%) — CI gate fails   |
| 2    | DB connection failed / SQL error                                     |
| 3    | At least one column exceeds **hard** threshold (10%) — boot guard fails |

### 3.1 Two thresholds — why?

**Soft (5%)** is the CI gate. PRs that push the catalogue NULL ratio
above 5% on any critical column fail the build via
`tests/unit/catalog/test_completeness_audit.py` and the dedicated
step in `.github/workflows/tests.yml`. The intent is to catch drift
early.

**Hard (10%)** is the boot guard. `docker/entrypoint.sh` runs the
audit in `--boot-guard` mode after `alembic upgrade head`. If any
critical column is above 10% the container refuses to hand off to
uvicorn. This is fail-closed catastrophe prevention: a broken catalogue
ingest must not boot a production API that would silently filter every
recipe for hypertensive / diabetic / CKD users.

Override (NOT recommended in prod): `SKIP_CATALOG_BOOT_GUARD=1`.

---

## 4. When to run

- **Pre-deploy**: every PR that touches `app/plan/application/layer1_eligibility.py`, condition_gates, or catalog ingest.
- **Weekly cron** (optional): hits `/metrics` to publish `catalog_null_ratio{column=...}` for Grafana.
- **After bulk ingest**: any `seed_recipes.py` or `merge_catalog_batches.py` run.
- **On user-visible empty-result complaint**: e.g. a hypertensive user reports "no recipes available" — audit first, blame algorithm second.

---

## 5. How to interpret

| Result                            | Action                                   |
|-----------------------------------|------------------------------------------|
| All OK                            | Nothing to do.                           |
| `sugar_g` > 5%, others OK         | Backfill carbs/sugar (priority diabetes).|
| `sodium_mg` > 5%                  | Backfill (hypertension + ckd impacted).  |
| `protein_g` > 5%                  | Backfill (ckd impacted).                 |
| Multiple > 10%                    | STOP. Catalogue ingest pipeline broken.  |

---

## 6. Backfill protocol

### 6.1 Diagnose
1. Identify offending rows: `SELECT id, name_en FROM recipes WHERE <col> IS NULL`.
2. Sample-inspect 3–5 rows to determine the cause class:
   - Component graph missing macros → upstream `foods` issue.
   - Component graph complete but aggregation skipped → re-resolution needed.
   - LLM-generated rows with hallucinated nulls → batch regenerate.

### 6.2 Re-resolve from components
1. `python -m scripts.resolve_ingredients --recipe-ids=<csv>` to recompute
   macros from the existing component graph.
2. Re-run audit. If still breached → go to 6.3.

### 6.3 USDA / FoodData Central lookup fallback
For rows where components are themselves NULL, the canonical source of
truth is **USDA FoodData Central** (https://fdc.nal.usda.gov/). Workflow:
1. Map each missing food to an FDC ID (manual or via `scripts/seed_foods.py --usda-lookup`).
2. Ingest the FDC nutrient panel into `foods` (per-100g basis, standardised units).
3. Re-resolve recipes (step 6.2).

### 6.4 OpenAI batch regeneration (last resort)
For rows where USDA has no match (regional / composite dishes):
1. Use `scripts/generate_recipes_round3_2026_06_01.py` (or the latest
   batch script) as the template.
2. Run in batch mode (50% cheaper than realtime). Cost cap applies
   per ADR-0004.
3. **Validate every row before merge** with
   `scripts/merge_catalog_batches.py` — its rejection log catches
   missing critical columns and prevents NULL propagation.
4. Re-run audit. Expect `OK`.

### 6.5 If still breached after 6.4
Stop. The catalogue ingest pipeline itself is broken. Open an incident,
do NOT redeploy. Inspect the most recent migration / catalogue script
diff for accidental column drops or transform bugs.

---

## 7. Metrics

`catalog_null_ratio{column="sugar_g"}` exported via Prometheus.

Suggested alert:

```yaml
- alert: CatalogNullRatioHigh
  expr: catalog_null_ratio > 0.05
  for: 1h
  annotations:
    summary: "{{ $labels.column }} NULL ratio above 5% in recipes"
```

---

## 8. References

- Source code: `scripts/catalog_completeness_audit.py`
- Metric: `app/core/metrics.py` `CATALOG_NULL_RATIO`
- Policy origin: R6 fail-closed change (Layer 1, 2026-06-03)
- Related: `docs/adr/0001-canonical-condition-vocabulary.md`
