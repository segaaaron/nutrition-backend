# Catalog Round 3 — 2026-06-01

Final closure of red-gap conditions in the meals catalog. Honest count.

## Inputs

- Master pre-round3: 33,069 recipes (`nova_meals_catalog.cleaned.json`)
- Vocab source of truth: `app/shared/domain/vocabularies.py`
- Generator: `scripts/generate_recipes_round3_2026_06_01.py`

## Per-bucket result (target vs accepted vs rejected)

| Bucket                | Target | Generated | Accepted | Rejected | Dedup vs master |
|-----------------------|------:|----------:|---------:|---------:|----------------:|
| ibd                   |  100  |    100    |    80    |     0    |       20        |
| hyperthyroidism       |  100  |    100    |    90    |     0    |       10        |
| chronic_insomnia      |  100  |    100    |   100    |     0    |        0        |
| diabetes_t1           |  200  |    200    |   170    |     0    |       30        |
| vitamin_d_deficiency  |   60  |     60    |    40    |     0    |       20        |
| overweight            |  135  |    143    |   122    |     0    |       21        |
| gout (positive)       |  100  |    100    |    50    |     0    |       50        |
| liquid extras (wl/fl) |   30  |     30    |    12    |    18    |        0        |
| diabetes_t1 snacks    |   25  |     25    |    25    |     0    |        0        |
| **Total**             | **850**| **858** | **689** |  **18**  |    **151**      |

Validator rejections (18) were all liquid drinks falling under the 30 kcal floor (ultra-light hydration teas/waters with `kcal_out_of_range=8..28`). Acceptable trade-off: floor preserves macro signal integrity per ADR-0001.

Cross-batch name dedup eliminated 151 collisions (mostly overweight/diabetes overlap with prior condition_helpful bucket). No silent expansions — every collision recorded in `scripts/generate_recipes_round3_2026_06_01_rejections.log`.

## Catalog delta

| Stage                              | Count |
|------------------------------------|------:|
| Pre-round3                         | 33,069 |
| + merge (round3 + re-checked prior batches) | 33,816 |
| – legal cleanup (whey/mass gainer residual) | 33,758 |
| – dedup names                      | 33,758 |
| **Final**                          | **33,758** |

Net delta vs starting catalog: **+689 recipes** (round3 contribution, isolated by ID prefix `nova_meal_r3_`). Legal cleanup removed 58 prior-batch contamination (40 whey + 18 mass gainer) — none from round3 (validator caught upstream).

## Coverage table (final, 9 closed buckets)

| Condition              | Recommended | Contraindicated |
|------------------------|------------:|----------------:|
| ibd                    |     80      |       0         |
| hyperthyroidism        |     90      |       1         |
| chronic_insomnia       |    101      |       0         |
| diabetes_t1            |    195      |       0         |
| vitamin_d_deficiency   |     80      |       0         |
| overweight             |    222      |       0         |
| gout                   |    143      |     703         |

Gout's high contraindicated count is correct: catalog enforces `purine=high` → auto-contraindicate (sardines, tuna, anchovies, organ meats wherever they appear).

## Files written

- `scripts/generate_recipes_round3_2026_06_01.py` (generator, 686 lines)
- `scripts/generate_recipes_round3_2026_06_01_rejections.log` (audit trail)
- `data/meals/round3_batch_2026_06_01.json` (689 accepted recipes)
- `data/meals/nova_meals_catalog.cleaned.json` (final, 33,758)
- `data/meals/nova_meals_catalog.cleaned.json.pre_round3_2026_06_01.bak` (rollback)

## Files modified

- `scripts/merge_catalog_batches.py` — added `ROUND3` path at end of merge tuple.

## Validation

- `uv run python -m pytest tests/catalog/ -q` → **7 passed**.
- Macro consistency ±5%, enum closure, allergen detection, supplement scrub, medical-claim scrub all green.
- All `regions` ⊆ `{us, ca, eu, uk, latam}`; all `recommended_for_conditions` ⊆ ADR-0001 25-canonical.
- `pregnancy_safe` default false; only true on hydrating liquids and bland breakfasts.
- `firebaseImageUrl` (placeholder GCS) preserved.

## Honest limitations

- 18 ultra-light hydration drinks dropped by kcal floor — acceptable.
- 151 cross-bucket name collisions resolved by silent dedup — no name disambiguation needed (collisions all from same bucket family, e.g. `Tofu Salteado con Brócoli` already existed in condition_helpful PCOS bucket).
- `diabetes_t1` recommended bucket (195) shared with `diabetes_t2` per nutrient-gate symmetry. Insulin-managed portion guidance lives at UI layer, not recipe layer.
