# NOVA Vision AI — Golden Set

Scaffold for the vision pipeline evaluation golden set (item #31).

The golden set is **the** regression gate for the vision cascade
(`VISION_CASCADE_ENABLED`). Until ≥100 curated entries exist and pass with
tolerance, the cascade stays OFF (per ADR-0004 and `docs/PROJECT_STATE.md`).

---

## Target distribution (100 platos)

| Bucket | Count | Regions sampled |
|---|---|---|
| Breakfast (LatAm) | 40 | PE, MX, AR, CO, CL, BR |
| Lunch (LatAm) | 30 | PE, MX, AR, CO, CL, BR |
| Dinner (LatAm) | 20 | PE, MX, AR, CO, CL, BR |
| Snacks (LatAm) | 10 | PE, MX, AR, CO, CL, BR |
| **Total** | **100** | — |

Regional sampling target inside each bucket: roughly proportional to user signup
distribution forecast (Peru-heavy initially: ~35% PE, ~20% MX, ~15% CO, ~10% AR,
~10% CL, ~10% BR). Adjust as real signup data accumulates.

---

## Per-entry structure

Each entry lives as one JSON object inside `entries/<id>.json` (or appended to
a single `entries.jsonl`, either form acceptable). Required fields:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable slug, e.g. `pe_breakfast_pan_palta_001` |
| `image_path` | string | Relative to `docs/qa/golden_set/images/` |
| `ground_truth.kcal` | int | Nutritionist-reviewed |
| `ground_truth.protein_g` | number | Decimal one place |
| `ground_truth.carbs_g` | number | Decimal one place |
| `ground_truth.fat_g` | number | Decimal one place |
| `ground_truth.ingredients` | array of `{name, portion_g}` | Lowercased Spanish names |
| `ground_truth.region` | enum | `pe \| mx \| ar \| co \| cl \| br` |
| `ground_truth.meal_time` | enum | `breakfast \| lunch \| dinner \| snack` |
| `tolerance.kcal_pct` | number | Default 0.15 (±15%) |
| `tolerance.macro_pct` | number | Default 0.20 (±20%) |
| `notes` | string \| null | Optional QA context |

Validated against `schema.json` (JSON Schema 2020-12).

---

## Curation workflow

1. Source image (own photo or licensed stock with redistribution rights).
2. Nutritionist labels: per ingredient → portion_g → macros from USDA / Tabla Peruana / TACO.
3. Aggregate kcal + macros from ingredient breakdown.
4. Tolerance: defaults per table above; tighten if dish is unambiguous.
5. Append entry, run `make eval-validate` (validates against schema).
6. Run `RUN_GOLDEN_SET=true pytest tests/eval -m eval` to see pipeline score.

---

## CI gate (deferred)

When golden set ≥100 entries:

- Run `tests/eval/test_vision_pipeline_eval.py` nightly against staging.
- Per-bucket pass rate must be ≥0.90 (90% of entries within tolerance).
- Aggregate kcal MAE must be ≤120 kcal.
- Aggregate macro MAE ≤15 g per macro.
- Per-ingredient precision ≥0.75, recall ≥0.70.
- Regression alert if any bucket pass rate drops > 5 percentage points vs last run.

Until those numbers stabilize on staging, the cascade flag stays OFF.

---

## Sample entries

See `sample_entries.json` for 5 representative entries demonstrating schema.
Real curation pending owner manual review (nutritionist input required —
NOT an AI task).
