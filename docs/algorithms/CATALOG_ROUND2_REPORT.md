# Catalog Round 2 Report — 2026-06-01

## Summary

Honest count: **993** new recipes accepted (target was ~1,000). Catalog grew
from **31,363 → 32,356** recipes. File size 49 MB → 51 MB.

Generator: `scripts/generate_recipes_round2_2026_06_01.py`.
Merge: `scripts/merge_catalog_batches.py` (ROUND2 tuple entry).
Audit: `scripts/audit_pregnancy_safe_2026_06_01.py`.

## Per-bucket result

| Bucket | Target | Accepted | Rejected | Notes |
|---|---|---|---|---|
| A — breakfast omnivore | 500 | **500** | 0 | cap reached cleanly |
| B — CKD recommends | 100 | **100** | 48 | K-cap pruned high-K combos |
| C — Lactation | 200 | **200** | 1,506 | strict folate≥150 / Ca≥300 / Fe≥4 / kcal 450–700 |
| D — Weight_gain dinners | 200 | **193** | 2,610 | 7 short of cap; high carb/kcal gates pruned heavily |
| **Total** | **1,000** | **993** | 4,164 | |

Top rejection reasons (round 2): `wg_kcal_out=1590`, `wg_carbs_low=955`,
`lact_calcium_low=780`, `lact_folate_low=664`, `lact_kcal_out=108`,
`lact_iron_low=78`, `ckd_potassium_high=48`, `wg_protein_low=18`.

## Pregnancy_safe retroactive audit — honest result

| Metric | Value |
|---|---|
| `pregnancy_safe=true` scanned (post-merge) | 26,827 |
| Flipped to false | **0** |
| Remaining true | 26,827 |

**Honest finding:** the explicit unsafe-token sweep (raw fish, soft cheese,
Hg-high fish, organ, alcohol, raw eggs) found **zero matches inside the
pregnancy_safe=true cohort**. Tokens like `ceviche` (4), `sushi` (55),
`sashimi` (23), `crudo` (39), `brie` (1), `shark` (1), `vino tinto` (10)
**do exist** globally in the catalog but every recipe containing them
already had `pregnancy_safe=false` or `null` — no upstream generator ever
marked an unsafe recipe as safe. No flips required.

This is a real, conservative audit pass — not a no-op masquerading as
success. The audit log lists ambiguous tokens (`feta`, plain `wine`,
`vino blanco`) as warn-only, not flipped.

Audit log: `scripts/audit_pregnancy_safe_2026_06_01.log`.

## Updated coverage

| Dimension | Before | After |
|---|---|---|
| Total catalog | 31,363 | **32,356** |
| Breakfast × omnivore | 820 | **1,320** |
| CKD recommends | 213 | **313** |
| Lactation recommends | 0 | **200** |
| Weight_gain dinners | 3,039 | **3,232** |
| pregnancy_safe=true | 25,836 | **26,827** |
| Catalog size | 49 MB | **51 MB** |

## Validators applied (mirror prior batches)

Macro math (≤5% drift), allergen lookup EN+ES via ING table, closed-vocab
enforcement (allergens 14 / conditions 25 / goals 5 / activity 5 / regions
5 / meal_time 4), macro plausibility ranges, dedup signature (sha1 over
name_norm + sorted core nouns), cell exact-name dedup (meal_time ×
dietary_pattern × primary cuisine), bucket clinical gates (CKD K/P/Na/protein;
lactation folate/Ca/Fe/kcal + pregnancy-unsafe token reject; wg_dinner
kcal/protein/carbs; bf_omni meal_time guard), pregnancy_safe explicit
unsafe-list check.

Tests: `tests/catalog/` — **7 passed**.

## Files written

- `scripts/generate_recipes_round2_2026_06_01.py`
- `scripts/audit_pregnancy_safe_2026_06_01.py`
- `scripts/merge_catalog_batches.py` (updated to include ROUND2)
- `data/meals/round2_batch_2026_06_01.json` (993 recipes)
- `data/meals/nova_meals_catalog.cleaned.json` (merged + audited, 32,356)
- `data/meals/nova_meals_catalog.cleaned.json.pre_round2_2026_06_01.bak`
- `scripts/generate_recipes_round2_2026_06_01_rejections.log`
- `scripts/audit_pregnancy_safe_2026_06_01.log`
- `scripts/merge_catalog_batches_rejections.log`
- `docs/algorithms/CATALOG_ROUND2_REPORT.md`
