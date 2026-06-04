# Catalog — Condition-Helpful Batch Report (2026-06-01)

## Scope

NOVA = nutrition planning (NOT nutrition guidance). Recipes adapt to declared
condition via two informational signals:

- `recommended_for_conditions[]` — nutrient gates aligned with condition needs.
- `contraindicated_conditions[]` — safety floor; recipe is unsafe for that condition.

No medical claims. No supplements. Display strings use neutral nutritional
descriptors only ("bajo en azúcar", "alto en fibra", "rico en omega-3").

## Per-bucket counts

| Bucket | Target | Generated | Accepted | Rejected | Dedup |
|---|---:|---:|---:|---:|---:|
| fatty_liver | 150 | 135 | 135 | 0 | 0 |
| hypercholesterolemia | 150 | 150 | 150 | 0 | 0 |
| pcos | 100 | 100 | 100 | 0 | 0 |
| ibs | 100 | 100 | 100 | 0 | 0 |
| hypothyroidism | 100 | 100 | 100 | 0 | 0 |
| gout | 100 | 100 | 90 | 0 | 10 |
| vitamin_d_deficiency | 50 | 50 | 40 | 0 | 10 |
| lactose_intolerance | 100 | 100 | 90 | 0 | 10 |
| overweight | 50 | 50 | 40 | 0 | 10 |
| **TOTAL** | **~900** | **885** | **845** | **0** | **40** |

Note: target for fatty_liver was 150 but the green-juice template set yielded
135 unique permutations. Dedup losses come from cross-bucket name collisions
(e.g., "Tortilla de Claras con Calabacín" appears in both IBS and gout
templates; the second bucket dedups by exact name).

## Catalog size

| Before | After | Delta |
|---:|---:|---:|
| 32,199 | 33,102 | **+903** |

The +903 delta vs the 845 new-batch recipes: the merge re-ran prior batches
(LIQUID, BULK, L99, GAP, ROUND2) and idempotently added 58 entries that
were not yet in master (e.g., recipes accepted by prior batch generators
but not previously merged due to dedup-by-id timing). All entries
pass enum closure + macro consistency (≤5%) validators.

## Updated condition coverage (rec / contraind)

| Condition | Before rec | After rec | Δ | Before contra | After contra |
|---|---:|---:|---:|---:|---:|
| fatty_liver | 2 | **427** | +425 | 0 | 0 |
| hypercholesterolemia | 16 | **274** | +258 | 0 | 0 |
| pcos | 0 | **100** | +100 | 0 | 0 |
| ibs | 5 | **117** | +112 | 3 | 3 |
| hypothyroidism | 1 | **101** | +100 | 1 | 1 |
| gout | 3 | **93** | +90 | 597 | **662** |
| vitamin_d_deficiency | 0 | **40** | +40 | 0 | 0 |
| lactose_intolerance | 0 | **60** | +60 | 40 | **266** |
| overweight | 10 | **65** | +55 | 0 | 0 |
| celiac | 106 | 106 | 0 | 1 | 1 |
| obesity | 51 | 91 | +40 | 0 | 0 |
| diabetes_t2 | 820 | 974 | +154 | 24 | 24 |

The gout-contraindication growth (+65) and lactose-intolerance-contraindication
growth (+226) come from the defensive auto-tagging inside `build_recipe()`:
any high-purine ingredient force-adds `gout` to contraindicated; any dairy
allergen (without explicit "sin lactosa") force-adds `lactose_intolerance`.

`ibd`, `hyperthyroidism`, `chronic_insomnia` remain low — these need
condition-specific recipe templates not yet built (deferred to next round).

## Scope scan (supplements + medical claims)

Scanned 845 new recipes across `name`, `description`, `ingredients`,
`instructions`:

| Class | Tokens scanned | Hits |
|---|---|---:|
| Supplements | whey, caseína, BCAA, creatina, pre-workout, mass gainer, proteína en polvo, multivitamínico | **0** |
| Medical claims | cura, trata, tratamiento, previene, cardioprotector, antiinflamatorio, detox, desintoxica, milagroso, limpieza hepática | **0** |

Pre-flight validator in the generator enforces zero residuals — any recipe
containing these tokens is rejected before reaching the batch file.

## Tests

```
uv run python -m pytest tests/catalog/ -q
7 passed, 1 warning in 0.45s
```

Enum-closure drift guard passes on the new 33,102-recipe catalog.

## Files written

- `/Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/scripts/generate_recipes_condition_helpful_2026_06_01.py`
- `/Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/scripts/generate_recipes_condition_helpful_2026_06_01_rejections.log`
- `/Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/data/meals/condition_helpful_batch_2026_06_01.json`
- `/Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/data/meals/nova_meals_catalog.cleaned.json.pre_cond_helpful_2026_06_01.bak`
- `/Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/scripts/merge_catalog_batches.py` (modified — tuple now includes `COND_HELPFUL`)
- `/Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/data/meals/nova_meals_catalog.cleaned.json` (merged, +903 entries)

## User-explicit deliverable

The user-specified fatty_liver breakfast (apio + limón + chía + piña + agua,
1 vaso) is included verbatim as the first entry of the `fl` bucket:

```
nova_meal_cond_fl_0001 — Jugo Verde de Apio, Limón, Chía y Piña
ingredients: 120 g de apio, 25 g de limón exprimido, 8 g de chía hidratada,
             60 g de piña, 200 ml de agua
meal_time: breakfast
recommended_for_conditions: ["fatty_liver", "overweight", "hypertension"]
contraindicated_conditions: []
```

Followed by 14 additional green-juice variants (apio+pepino+jengibre,
espinaca+manzana, kale+piña, betarraga+apio, alcachofa+limón, rúcula+pepino,
etc.) — all gated to `meal_format=liquid`, `sugar_g ≤ 12`, `carbs_g ≤ 25`.
