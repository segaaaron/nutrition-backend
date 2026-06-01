# NOVA Nutrition — Clinical Catalog Audit (Pre-Launch)

**Audit date:** 2026-06-01
**Auditor:** NOVA-Core (clinical nutritionist + DB engineer)
**Scope:** `data/meals/nova_meals_catalog.cleaned.json` + `data/meals/nova_meals_catalog.json`
**Standards:** ADR-0001 Appendix A (revised), ADR-0007/0008 dual-language, spec §6/§7
**Result:** **NO-GO for production** as-is. Blocking enum drift + clinical contradictions + zero algorithmic-coverage on 8 micronutrient fields.

---

## 1. Files at a glance

| File | Entries | Schema-complete | Has `_audit` provenance | Has `regions[]` |
|------|--------:|-----------------|--------------------------|-----------------|
| `nova_meals_catalog.cleaned.json` | **2000** | 2000 / 2000 | yes | yes (100% = `["latam"]`) |
| `nova_meals_catalog.json` (raw) | **2000** | 2000 / 2000 | no | **0 / 2000 (missing)** |

The cleaned file is the prod candidate. The raw file is **kept only as historical input** and must not be loaded by the seeder.

---

## 2. Integrity (cleaned file)

| Check | Result |
|-------|--------|
| Duplicate IDs | **0** |
| Duplicate names (case-insensitive) | **4** — see table below |
| Missing top-level required fields | **0** |
| `regions[]` empty/missing | **0** |
| JSON parses | yes |

### Duplicate names (cleaned)

| Name | Count |
|------|------:|
| `mujadara libanesa de lentejas y arroz` | 3 |
| `bowl de atún con quinoa y edamame` | 2 |
| `sopa vietnamita pho de pollo` | 2 |
| `lomo saltado peruano magro` | 2 |

→ Not blocking, but the discovery/search UX will show "the same dish" twice. Rename or merge before launch.

---

## 3. Enum drift — **BLOCKING**

The cleaned file still has **4 017 enum violations** across two fields:

| Field | Total invalid | Top invalid values (count) |
|-------|---------------:|----------------------------|
| `suitableForActivity` | 2 204 | `moderate` (1 193), `active` (1 011) |
| `targetGoals` | 1 813 | `maintain_weight` (470), `build_muscle` (468), `general_health` (460), `gain_weight` (415) |

`targetGoals` in the cleaned file uses the **old vocabulary** entirely — there is **not a single** recipe tagged with the canonical `maintain`, `muscle_gain`, `weight_gain`, `health`, or even `weight_loss` (415 entries say `weight_loss` but Python counted them under the old enum; only `weight_loss` happens to overlap). The seeder will reject all 2 000 entries against the Postgres enum.

The raw file is worse: **6 748 enum violations** including 826 occurrences of `cardiovascular_disease`, 408 `kidney_disease`, plus invented values (`sarcopenia`, `metabolic_syndrome`, `menopause`, `cognitive_health`, `anti_inflammatory`, `general_wellness`, …) — all need a mapping table or to be dropped.

### Required mapping (raw → canonical)

| Old | Canonical | Affected rows (raw) |
|-----|-----------|--------------------:|
| `maintain_weight` | `maintain` | 470 |
| `build_muscle` | `muscle_gain` | 468 |
| `gain_weight` | `weight_gain` | 415 |
| `general_health` | `health` | 460 |
| `moderate` (activity) | `moderately_active` | 1 193 |
| `active` (activity) | `very_active` (or `moderately_active`?) | 1 011 |
| `cardiovascular_disease` (cond) | `ischemic_heart_disease` | 826 |
| `kidney_disease` (cond) | `ckd` | 408 |
| `diabetes_type_2` | `diabetes_t2` | 422 |
| `high_cholesterol` | `hypercholesterolemia` | 15 |
| `anemia` | `iron_deficiency_anemia` | 25 |
| `egg_allergy`, `soy_allergy`, `fish_allergy`, `dairy_allergy`, `peanut_allergy`, `gluten_intolerance` | **drop from `contraindicatedConditions`** — these belong in `allergens[]` only | ~130 |
| `irritable_bowel_syndrome` | `ibs` | 3 |
| `sarcopenia`, `muscle_recovery`, `muscle_hypertrophy`, `muscle_building` | **drop** (not in 25-condition universe) | ~170 |
| `metabolic_syndrome`, `menopause`, `cognitive_health`, `anti_inflammatory`, `general_wellness`, `immune_support`, `digestive_health`, `digestive_issues`, `malnutrition`, `underweight` | **drop** | ~400 |

The cleaned file already mapped `recommendedForConditions` correctly — that part was migrated. It is only `targetGoals` + `suitableForActivity` that were missed.

---

## 4. Coverage

### mealTime — **CRITICAL GAP**

| mealTime | Count |
|----------|------:|
| breakfast | 600 |
| lunch | 800 |
| dinner | 600 |
| **snack** | **0** |

**Zero snacks in the entire catalog.** Algorithms-expert cannot build a 4-meal daily plan. Need ~300 snack entries before launch.

### targetGoals (using actual cleaned values, pre-remap)

| Goal | Count | kcal min / max / mean |
|------|------:|-----------------------|
| weight_loss (canonical) | 415 | 167 / 606 / 352 |
| build_muscle → muscle_gain | 468 | 249 / 900 / 574 |
| maintain_weight → maintain | 470 | 179 / 706 / 475 |
| gain_weight → weight_gain | 415 | 446 / 904 / 730 |
| general_health → health | 460 | 180 / 742 / 445 |

Goal kcal distributions are clinically coherent (weight_loss caps at 606, weight_gain floors at 446).

### regions — **CRITICAL FOR US LAUNCH**

| region | Count |
|--------|------:|
| latam | 2 000 |
| us, ca, eu, uk | 0 |

If the iOS app launches in the US App Store this catalog has **zero** US-tagged content. Either (a) re-tag a large subset as multi-region (`["latam","us"]` for dishes that travel — quinoa bowl, oatmeal, salmon, etc.), or (b) explicitly gate the US launch on a separate catalog batch.

### Conditions — coverage by `recommendedForConditions` (cleaned)

| Condition | recipes |
|-----------|--------:|
| ischemic_heart_disease | 858 |
| diabetes_t2 | 422 |
| hypertension | 185 |
| obesity | 56 |
| iron_deficiency_anemia | 27 |
| hypercholesterolemia | 15 |
| ckd | 13 |
| overweight | 10 |
| celiac | 6 |
| gout | 3 |
| fatty_liver | 2 |
| ibs | 2 |
| hypothyroidism | 1 |

**12 of 25 conditions have ZERO matching recipes:**
`athletic_load, chronic_insomnia, diabetes_t1, dyslipidemia, hyperthyroidism, ibd, lactation, lactose_intolerance, mild_depression, pcos, pregnancy, vitamin_d_deficiency`

Several are launch-critical (pregnancy, lactation, lactose_intolerance, diabetes_t1) — see §8.

### Allergens

`lupin` is never tagged (cleaned). For EU compliance every recipe with chickpea-flour/lupin-flour bakery must be reviewed. Also `sulphites` (29) and `molluscs` (27) look thin; check that wine-based reductions and squid/octopus dishes really do count.

---

## 5. Macro math — **PASSES**

| Sample | Size | Mean error | Within ±2 % | Within ±5 % |
|--------|-----:|-----------:|------------:|------------:|
| Random | 100 | **0.0 %** | 100 / 100 | 100 / 100 |
| Full scan (>5 %) | 2 000 | — | 0 mismatches | 0 mismatches |

Macros are *exact* — `P×4 + C×4 + F×9 == calories` to integer precision on every recipe. This is the strongest part of the catalog. The math constraint from spec §6 (`MACRO_TOLERANCE = 0.02`) is satisfied with margin to spare.

**Outliers / extreme values:** none. kcal range 167–904, protein ≤ 70 g, fat ≤ 42 g — all clinically plausible.

---

## 6. Clinical contradictions — **130 in cleaned, 245 in raw**

### Cleaned file breakdown

| Pattern | Count | Example |
|---------|------:|---------|
| `recommendedForConditions: diabetes_t2` with carbsG > 60 | **87** | `nova_meal_b04_043` carbsG=70 |
| Tree-nut ingredient present, `tree_nuts` NOT in allergens | **37** | `nova_meal_b01_004` (nueces); `nova_meal_b01_041` (almendras); `nova_meal_b02_001` (pistachos) |
| `recommendedForConditions: hypertension` with sodium-heavy ingredient | **6** | `nova_meal_b02_042` lists `sal` |

The 87 diabetes_t2 entries with >60 g carbs are the highest-liability rows — a diabetes_t2 user being recommended a 70 g-carb meal will spike. **Either drop `diabetes_t2` from `recommendedForConditions` on these 87 rows or rebalance the recipe.**

Tree-nut omissions are a regulatory issue in the US (FALCPA) and EU (1169/2011 Annex II). All 37 must be patched before App Store submission.

### Raw file additional patterns (will leak into cleaned if a re-import happens)

- 96 recipes with `pasta` not flagged gluten
- 33 with `mantequilla` not flagged dairy
- 22 with `pan` not flagged gluten
- 9 with `yogur` not flagged dairy
- 8 with `bulgur` not flagged gluten
- 5 with `cuscús` not flagged gluten

These were **fixed in the cleaned file** (gluten count rose from 620 → 799, dairy from 512 → 675, sesame from 22 → 355). Good. Just make sure nobody re-imports the raw.

---

## 7. Fields missing for `nova-nutrition-algorithms-expert` — **BLOCKING for personalization**

Every recipe lacks **all 10** of the algorithm-critical fields:

| Field | Recipes missing | Needed for |
|-------|----------------:|------------|
| `glycemicIndex` | 2 000 / 2 000 | diabetes_t2 ranking, pcos |
| `fiber_g` | 2 000 / 2 000 | fiber-target compliance, ibs |
| `sodium_mg` | 2 000 / 2 000 | hypertension, ckd |
| `potassium_mg` | 2 000 / 2 000 | ckd, hypertension |
| `phosphorus_mg` | 2 000 / 2 000 | ckd |
| `iron_mg` + `heme_pct` | 2 000 / 2 000 | iron_deficiency_anemia, pregnancy |
| `calcium_mg` | 2 000 / 2 000 | pregnancy, lactation |
| `omega3_mg` (EPA+DHA) | 2 000 / 2 000 | ischemic_heart_disease, dyslipidemia |
| `embeddings` (1536-dim) | 2 000 / 2 000 | variety penalty + semantic search |

Without these, the algorithms-expert can only rank on (kcal, P, C, F, mealTime, goal). That degrades the recommender to a glorified macro filter — the entire clinical-personalization story collapses.

---

## 8. Prioritized action plan

### 🔴 Blocking (must ship before App Store / Play Store submission)

1. **Re-map `targetGoals`** (`maintain_weight→maintain`, `build_muscle→muscle_gain`, `gain_weight→weight_gain`, `general_health→health`) in cleaned. 1 813 row edits.
2. **Re-map `suitableForActivity`** (`moderate→moderately_active`, `active→very_active`). 2 204 row edits — confirm `active` mapping with PM (could be `very_active` *or* `moderately_active`).
3. **Generate ~300 snack entries** — algorithms cannot produce 4-meal plans without these.
4. **Fix 37 tree-nut allergen omissions** — FALCPA/EU 1169 compliance.
5. **Fix 87 diabetes_t2-recommended high-carb recipes** — drop the recommendation or rebalance.
6. **Decide `regions[]` policy for US launch.** Either re-tag a multi-region subset or gate the US launch.

### 🟡 Month 1 (data quality)

7. Backfill the **10 algorithm-critical fields** for all 2 000 recipes — start with `fiber_g`, `sodium_mg`, `glycemicIndex` (highest-leverage), then ckd-specific (`potassium_mg`, `phosphorus_mg`), then `embeddings`.
8. Add recipes for the **12 missing conditions** — at minimum **pregnancy, lactation, lactose_intolerance, diabetes_t1** (clinically critical), then `pcos, dyslipidemia, athletic_load`.
9. Resolve the **4 duplicate names**.
10. Delete or quarantine `nova_meals_catalog.json` (raw) so it cannot be re-imported.

### 🟢 Continuous

11. Expand `lupin`, `sulphites`, `molluscs` tagging review.
12. Add `chronic_insomnia` / `mild_depression` mood-food recipes (tryptophan, magnesium, omega-3).
13. Cross-region tagging once US copy is translated.

---

## 9. Handoff protocol with `nova-nutrition-algorithms-expert`

### What NOVA-Core (this audit role) produces & validates

- **In:** raw recipe drafts (from generator, scrapers, or human dietitians).
- **Out:** clinically-validated JSON conforming to ADR-0001 / ADR-0007 / spec §6.
- **Guarantees:** macro math ≤ 2 % error, enum-clean, allergen-complete, condition-safe.
- **Owns:** `matchingCriteria.*`, `nutritionProfile.*`, micronutrient backfill.

### What algorithms-expert produces & NOVA-Core validates

- Ranking outputs (top-N recipes for a user profile) — NOVA-Core spot-checks that no `contraindicatedConditions` leaks through.
- Variety/embedding scores — NOVA-Core reviews diversity weights so that clinical fit isn't sacrificed for novelty.
- A/B experiments — NOVA-Core signs off on clinical safety of any heuristic before it goes live.

### Expansion requests

When algorithms-expert needs more inventory (e.g. *"30 more recipes for CKD low-sodium dinner"*):

1. Algorithms-expert files a request with: `condition`, `mealTime`, `goal`, `kcal range`, `count`, `extra constraints` (`sodium_mg < 600`, `potassium_mg < 700`, `proteinG < 25`).
2. NOVA-Core drafts JSON batch following spec, runs internal self-checks 1–8.
3. Drop batch into `data/meals/expansions/<yyyymmdd>_<topic>.json`.
4. CI macro+enum+contradiction validator (to be built — see Month-1 #7) must pass.
5. Algorithms-expert re-indexes, embeddings recomputed.

### Shared contract (proposed addition to ADR)

A single `MealValidator` package consumed by **both agents**:
`app/shared/domain/meal_validator.py` exporting `validate(meal_dict) -> list[Violation]`. NOVA-Core gates writes with it; algorithms-expert gates reads with it before serving rankings. This guarantees no enum drift can re-enter the system once we patch the current 4 017 violations.

---

## 10. Bottom line

The catalog has **excellent macro precision** and **good cleaned-file allergen coverage**, but it is **not loadable** against the canonical Postgres enums, **lacks snacks entirely**, **leaks tree-nut allergens** on 37 recipes, **recommends 87 high-carb dishes to diabetics**, and **has none of the 10 fields** the personalization engine needs. Fix items 1–6 to unblock launch.
