# Catalog Finalization Report — 2026-06-01

Honest accounting of the finalization batch that closes remaining red/yellow
gaps and adds a positive pregnancy recommendation pool.

## Per-bucket target vs accepted vs rejected

| Bucket                  | Target | Generated | Accepted | Rejected | Dedup |
|-------------------------|-------:|----------:|---------:|---------:|------:|
| ibd_extra               |    +20 |        20 |       20 |        0 |     0 |
| hyperthyroidism_extra   |    +10 |        10 |       10 |        0 |     0 |
| vitamin_d_extra         |    +20 |        20 |       20 |        0 |     0 |
| lactose_extra           |    +40 |        40 |       35 |        0 |     5 |
| pregnancy_boost         |   +250 |       250 |      250 |        0 |     0 |
| **Total**               | **340**|   **340** |  **335** |    **0** | **5** |

Five lactose-extra recipes shared display names with the pre-existing catalog
and were dropped at the dedup gate — honoring "no duplicate names."

## Final catalog

| Stage                             |  Count |  Delta |
|-----------------------------------|-------:|-------:|
| Before merge                      | 33,758 |      — |
| After merge (8 batches re-scan)   | 34,151 |   +393 |
| After legal cleanup               | 34,093 |    −58 |
| After dedup-names pass            | 34,093 |      0 |

The merge added 335 finalization recipes + 58 stragglers from older batches.
The legal cleanup then removed 58 supplement-tainted recipes (40 whey, 18 mass
gainer) that had slipped in earlier. Net catalog growth: **+335**.

## Coverage updated

| Condition (recommended_for) | Before | After |
|-----------------------------|-------:|------:|
| ibd                         |     80 |   100 |
| hyperthyroidism             |     90 |   100 |
| vitamin_d_deficiency        |     80 |   100 |
| lactose_intolerance         |     60 |    95 |
| pregnancy                   |      0 |   250 |

- Pregnancy recommended pool: **250** recipes, **250** with `folate_ug`,
  `iron_mg`, `calcium_mg` populated (100%).
- All meet `folate_ug ≥ 150`, `iron_mg ≥ 4`, `calcium_mg ≥ 250` per portion.
- Pregnancy-safe (boolean) total: 27,162 (no change in semantics — the boost
  set is a strict positive subset).

## Validator rejection breakdown

During iterative generation, the pregnancy boost surfaced two recurring fails:

1. `pregnancy_block_token=crudo` — false positive on the safety paragraph in
   `description` that itself said "sin pescados crudos." Resolved by
   word-boundary regex + rephrased description.
2. `folate_low=<n>` — four breakfast specs could not hit 150 µg folate with
   only oat/yogurt/seeds. Replaced with espinaca + lentejas + yogur
   constructions that all clear the gate.

Final batch run: **0 macro drift, 0 enum drift, 0 supplement, 0 medical claim,
0 pregnancy block, 0 micro-nutrient short**.

## Tests

`uv run python -m pytest tests/catalog/ -q` → **7 passed**.

## Files written

- `scripts/generate_recipes_finalization_2026_06_01.py`
- `data/meals/finalization_batch_2026_06_01.json` (335 recipes)
- `scripts/generate_recipes_finalization_2026_06_01_rejections.log`
- `data/meals/nova_meals_catalog.cleaned.json.pre_finalization_2026_06_01.bak`
- `data/meals/nova_meals_catalog.cleaned.json` (34,093 recipes — final)
- `scripts/merge_catalog_batches.py` (tuple extended with `FINAL`)
- `docs/algorithms/CATALOG_FINALIZATION_REPORT.md` (this file)
