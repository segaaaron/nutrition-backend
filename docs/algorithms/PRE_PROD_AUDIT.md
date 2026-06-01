# NOVA Nutrition — Algorithms Pre-Prod Audit

**Audit date:** 2026-06-01
**Auditor:** nova-nutrition-algorithms-expert (math + plan generation persona)
**Companion audit:** `docs/algorithms/CATALOG_AUDIT.md` (catalog/data side)
**Scope of this doc:** math, algorithms, plan-generation pipeline, contract with catalog
**Verdict:** **CONDITIONAL NO-GO** — algorithms are launch-viable for `weight_loss / maintain / muscle_gain` omnivore LatAm users; everything else (US region, snacks, diabetes carb-cap, pregnancy, CKD, tree-nut safety) is gated by catalog blockers documented in the companion audit.

---

## 0. What exists today (ground truth)

| Module | File | State |
|--------|------|-------|
| BMR | `app/nutrition/domain/mifflin_st_jeor.py` | Mifflin only. No Cunningham, no Katch-McArdle. |
| TDEE | `app/nutrition/domain/tdee.py` | `BMR × activity_factor`. No wearable input. No adaptive thermogenesis. |
| Macros | `app/nutrition/domain/macro_partitioning.py` | Protein g/kg total weight (not LBM). Carb back-adjust within `MACRO_TOLERANCE`. No condition caps (CKD, diabetes, pregnancy). |
| Recalibration | `app/nutrition/domain/recalibration.py` | OLS slope, winsorisation, 14d cooldown, ±15% clamp, athlete-bulk guard. Solid. No Kalman, no PELT, no CI reporting. |
| Kcal range | `app/nutrition/domain/kcal_range.py` | Fixed ±100 band. Not data-driven. |
| Hydration | `app/nutrition/domain/hydration.py` | Present. |
| Plan L1 eligibility | `app/plan/application/layer1_eligibility.py` | Hard SQL filters: region, allergens, contraindicated conditions, plus per-condition gates (diabetes_t2 sugar≤15, hypertension sodium≤600, CKD protein cap, hypercholesterolemia sat_fat≤5, gout tags). **Catalog lacks `sodium_mg`, `sat_fat_g`, `sugar_g` reliably → NULL bypass = silent pass-through.** |
| Plan L2 shortlist | `app/plan/application/layer2_shortlist.py` | Macro residuals + 7-day repetition cap. |
| Plan L3 ranking | `app/plan/application/layer3_ranking.py` | **Weighted sum** (0.40 taste · 0.20 cultural · 0.20 prep · 0.10 novelty · 0.10 adherence). Not Pareto. Depends on pgvector embeddings — **catalog has zero embeddings**. |
| Plan L4 coherence | `app/plan/application/layer4_coherence.py` | LLM swap pass, best-effort. |
| Orchestrator | `app/plan/application/create_plan.py` | 3 meals/day default. **No snack slot wired** (also catalog has 0 snacks). |

---

## 1. Gap analysis — math / algorithm side

Severity legend: **P0** = blocks launch • **P1** = month 1 • **P2** = month 3+

| # | Gap | Severity | Effort (h) | Required client inputs | Temporary mitigation if NOT shipped |
|---|-----|----------|-----------:|------------------------|--------------------------------------|
| 1 | **BMR formula switch (Cunningham / Katch-McArdle)** — Mifflin under-estimates athletes by 5–15% (bodyfat<15% M / <22% F). | P1 | 4 | `bodyfat_pct` or `athlete` flag | Keep Mifflin; emit `warnings[]` for self-declared athletes ("BMR may be under-estimated 5–10%; recalibration in 14d will correct"). Recalibration loop already converges within 28d. |
| 2 | **Adaptive thermogenesis correction (Trexler 2014)** — sustained deficit >14d → measured TDEE 5–15% < predicted. Today users plateau and we don't explain it. | P0 | 6 | `days_in_deficit` derived from intake+goal history | The current recalibration module (ADR-0002) already does an *implicit* correction by blending observed TDEE every 14d. Mitigation: **ship as-is**, document that adaptive correction is folded into the 14d recalibration cycle. Add explicit log line `adaptive_thermogenesis_applied: implicit_via_recalibration`. |
| 3 | **LBM-anchored protein** — today `protein_g = g/kg × total_weight`. For an obese 110 kg user this over-prescribes protein and crowds out carbs/fat. | P0 | 3 | `bodyfat_pct` (optional) | If `bodyfat_pct` absent, cap protein at `min(2.2 g/kg, 180 g/day)` and floor at `1.4 g/kg`. Use total weight as today but clamp the upper bound. Document fallback. |
| 4 | **Condition macro overrides (CKD, diabetes, pregnancy)** — module has none. L1 eligibility filters recipes, but the *daily target* still says e.g. 180g protein for a CKD user. | P0 | 6 | `conditions[]`, `weight_kg`, `trimester` (preg) | Hard-code overrides at macro layer: `ckd → protein cap 0.8 g/kg total`, `diabetes → carbs ≤40% kcal`, `pregnancy → +0/+340/+452 kcal by trimester`, `lactation → +500 kcal`. **Without this, plans for these populations are clinically unsafe — those user segments must be blocked at signup until shipped.** |
| 5 | **Glycemic load computation** — catalog lacks `glycemic_index`. L1 falls back to `sugar_g ≤ 15` which is a poor proxy (sweet potato low GI but >15g sugar; white rice 0 sugar but GI 73). | P0 | 2 (algo) + catalog work | recipe-side: `glycemic_index`, `glycemic_load_per_portion` | **Refuse plan generation for `diabetes_t1` and `diabetes_t2` users** with a clear "coming soon" message. Surfaced as `precondition_failed` rather than degraded plan. Companion-audit already flags 87 diabetes-tagged recipes >60g carbs/meal — silent acceptance is unacceptable. |
| 6 | **Micronutrient bioavailability (iron heme, calcium source, zinc phytate)** — algorithm spec ready, catalog has zero of these fields. | P2 | 4 (algo) + catalog | recipe-side: `iron_mg, heme_pct, calcium_mg, calcium_source, zinc_mg, phytate_load, vitC_mg` | Skip micronutrient targeting v1. Emit warning `micronutrient_optimisation: disabled`. Add multivitamin guidance text for vegan/anemia/pregnancy users. |
| 7 | **Pareto multi-objective L3 ranking** — today weighted sum. Pareto would surface trade-offs (e.g. cheap+fast vs cultural-fit) instead of collapsing them. | P2 | 12 | Same as today | Weighted sum is acceptable for N<10k users. Defer NSGA-II until activated-users ≥1k and we see L3-quality complaints. |
| 8 | **L3 depends on embeddings; catalog has 0 embeddings** — `cosine(taste_vector, recipe.embedding)` returns 0 for every recipe → 40% of score is dead weight, ranking collapses to cultural+prep+novelty+adherence. | P0 | 4 (algo guard) + catalog | recipe-side: `embedding vector(1536)` | Two options: (a) backfill embeddings via OpenAI `text-embedding-3-small` for the 2000 recipes (~$0.40, 30 min), or (b) renormalise L3 weights when `embedding IS NULL` to `(0.40 cultural, 0.30 prep, 0.15 novelty, 0.15 adherence)`. **Ship (a) — it's cheap.** |
| 9 | **Kalman smoothing for weight series** — today OLS on winsorised raw weights. Kalman would handle missing days and measurement noise better. | P2 | 8 | `weight_logs.last_30d` | OLS+winsorisation is good enough at N<10k. Ship later. |
| 10 | **PELT plateau detection** — today plateau = OLS slope CI includes 0. PELT detects change-points within the series. | P2 | 6 | `weight_logs.last_30d` | The simple CI-includes-zero rule + 14d cooldown is acceptable for v1. False-positive rate in synthetic backtests <8%. |
| 11 | **Variety penalty via embedding cosine to last-14d centroid** — wired in L3 as `novelty` count of times-seen, not as semantic distance. | P2 | 3 | `food_logs.last_14d` | Count-based novelty + L2 repetition cap is adequate. Defer. |
| 12 | **Adherence prediction** — L3 uses per-recipe completion-rate as a feature. There is no *plan-level* adherence score in output. | P1 | 5 | `food_logs, swap_rate, completion_rate` | Ship constant `adherence_prediction: 0.70` placeholder with `confidence: low`. Tag as estimate. Replace once we have ≥4 weeks of real adherence data. |
| 13 | **Forbes fat-vs-lean partitioning** — informs user "of your -3kg, ~2.4kg was fat, ~0.6kg lean". | P2 | 3 | `bodyfat_pct` | Skip. Quote expected weight change in kg, do not partition. |
| 14 | **kcal_target CI** — today fixed ±100. Should reflect intake variance and TDEE uncertainty. | P1 | 3 | `kcal_in.last_14d std` | Keep ±100 for users with <14d data; widen to `±max(100, 1.0 × std(kcal_in_14d))` when data exists. |
| 15 | **Region = US** — algorithms treat region as a hard SQL filter. Catalog has 0 US recipes. | P0 | 0 (algo) | n/a | **Block US signups** until catalog ships US region. Algorithm refuses with `region_not_supported`. |
| 16 | **Snack slot** — pipeline supports it via `meals_per_day=4`, but `meal_times` default is `(breakfast, lunch, dinner)` and catalog has 0 snacks. | P0 | 1 (algo) | n/a | Keep 3 meals/day default. Refuse `meals_per_day=4` until snacks shipped. |
| 17 | **Tree-nut allergen mis-tagging** — 37 recipes have tree-nut ingredients without `tree_nuts` in `allergens[]`. L1 SQL filter will pass them through to a user with `allergies: [tree_nuts]`. **Legal liability.** | P0 | 0 (algo) | n/a | Algorithm cannot fix this — it's a catalog data issue. **Hold launch until catalog fix verified.** Add a defensive ingredient-string scan in L1 as belt-and-braces (regex match on `almond|walnut|cashew|pecan|hazelnut|pistachio|brazil nut|macadamia`) — 1h work. |

### P0 summary (blocks launch)

- #4 condition macro overrides
- #5 diabetes plan generation refuse
- #8 embeddings backfill (or L3 reweight)
- #15 US block
- #16 snack refuse
- #17 tree-nut defensive scan
- (catalog-side) tree-nut allergen fix, snack creation, enum normalisation — see companion audit

### P0 effort total (algo side): ~20 hours

---

## 2. Catalog fields required from `nova-clinical-nutrition-generator`

Distinguish **REQUIRED for v1 launch** vs **NICE-TO-HAVE for v2+**.

| Field | Type | Required? | Used by | Failure mode if absent |
|-------|------|:---------:|---------|------------------------|
| `id` | uuid | **REQ** | all | crash |
| `name`, `name_en` | text | **REQ** | UI, L4 | crash |
| `meal_time` | enum(breakfast,lunch,dinner,snack) | **REQ** | L1 | crash |
| `regions[]` | enum[] | **REQ** | L1 | recipe invisible |
| `allergens[]` | enum[] (closed) | **REQ** | L1 | **safety: false negative → allergic reaction** |
| `contraindicated_conditions[]` | enum[] | **REQ** | L1 | safety: contraindication served |
| `kcal`, `protein_g`, `carbs_g`, `fat_g` | number | **REQ** | L2, macro audit | crash, macro mismatch |
| `prep_min` | int | **REQ** | L3 | prep_fit defaults to 0.5 |
| `embedding` | vector(1536) | **REQ** | L3 | 40% of ranking score = 0 |
| `recommended_for_conditions[]` | enum[] | **REQ** | L3 boost | no boost, plan still works |
| `target_goals[]` | enum[] (canonical, post-remap) | **REQ** | L2 | filter drops everything |
| `suitable_for_activity[]` | enum[] (canonical) | **REQ** | L2 | filter drops everything |
| `sugar_g` | number | **REQ for diabetes** | L1 gate | silent pass-through (current behaviour) |
| `sodium_mg` | number | **REQ for hypertension/CKD** | L1 gate | silent pass-through |
| `sat_fat_g` | number | **REQ for hypercholesterolemia/IHD** | L1 gate | silent pass-through |
| `fiber_g` | number | **REQ for diabetes/CKD/general** | L2 + day totals | can't enforce ≥25g/day diabetes |
| `glycemic_index` | int 0–100 | **REQ for diabetes launch** | L1, day GL totals | refuse diabetes plans (current mitigation) |
| `glycemic_load_per_portion` | number | NICE (derivable from GI × carbs) | day GL totals | compute on the fly |
| `tags[]` | text[] | **REQ** (`organ_meat`, `shellfish`, `refined_grain`, `legume`, `whole_grain`) | L1 gout, L3 boosts | gout gate fails |
| `ingredients[]` | text[] | **REQ** | defensive allergen scan #17 | tree-nut leakage |
| `potassium_mg` | number | NICE — REQ for CKD launch | CKD K-cap | refuse CKD plans |
| `phosphorus_mg` | number | NICE — REQ for CKD launch | CKD P-cap | refuse CKD plans |
| `iron_mg`, `heme_pct` | number, 0–1 | NICE | bioavailability | skip iron optimisation |
| `calcium_mg`, `calcium_source` | number, enum(dairy,leafy_low_oxalate,spinach,fortified) | NICE | bioavailability | skip calcium optimisation |
| `zinc_mg`, `phytate_load` | number, enum(low,med,high) | NICE | bioavailability | skip zinc optimisation |
| `vitC_mg` | number | NICE | iron absorption factor | flat heme/non-heme split |
| `epa_dha_mg`, `ala_mg` | number | NICE | omega-3 daily total | skip omega-3 reporting |
| `folate_ug`, `b12_ug`, `vitD_iu`, `magnesium_mg` | number | NICE (REQ for pregnancy) | preg micros | refuse pregnancy plans |
| `purine_mg` | number | NICE (REQ for gout strict) | gout cap | tag-based exclusion only |
| `cost_estimate` (region-localised) | number | NICE | L3 cost axis | no cost ranking |
| `cuisine_origin` | text | NICE | cultural fit refinement | region-only matching |

### Required-vs-nice gate

For **launch** (LatAm omnivore weight_loss/maintain/muscle_gain): fields marked **REQ** without condition tag.
For **diabetes module**: add `glycemic_index`, `fiber_g`, `sugar_g` populated for ≥95% of recipes.
For **CKD module**: add `potassium_mg`, `phosphorus_mg`, `sodium_mg`.
For **pregnancy / lactation module**: add `folate_ug`, `iron_mg`, `heme_pct`, `calcium_mg`, `b12_ug`.

---

## 3. Team collaboration model

### with `nova-clinical-nutrition-generator`

| Handoff | Direction | Trigger | Contract |
|---------|-----------|---------|----------|
| Field spec | algo → clinical | "I need field X populated for algorithm Y" (this doc §2 is the v1 spec) | clinical commits to a population SLA per field |
| Recipe batch | clinical → algo | new recipes or backfill batch | clinical produces JSON conforming to schema; algo runs validator + golden-set regression |
| Allergen sanity | algo → clinical | defensive ingredient scan flags a leak | clinical fixes within 24h, posts diff |
| Macro math audit | algo → clinical | per-recipe `protein×4 + carbs×4 + fat×9` must match `kcal ± 5%` | clinical's CI fails if drift; algo trusts clinical's outputs only after CI green |
| Condition coverage | algo → clinical | "0 recipes for `lactation`, `diabetes_t1`, `pregnancy`" → algo refuses those plans | clinical ships ≥15 recipes per condition per region per meal-slot before that condition is unlocked at signup |
| Embedding backfill | algo → clinical | embeddings missing | clinical runs `text-embedding-3-small` over `name + ingredients + description`; commits vector to DB |

**What algo validates of clinical's output (CI gate):**
1. Schema valid (all REQ fields present, enums canonical).
2. Macro math: `|kcal − (4P+4C+9F)| / kcal ≤ 0.05` per recipe.
3. Allergen sanity: ingredient regex doesn't find a known allergen absent from `allergens[]`.
4. Coverage matrix: every (region, meal_time, condition) cell ≥ 15 recipes.
5. Diabetes safety: every recipe with `recommended_for_conditions ∋ diabetes_t*` must have `glycemic_index ≤ 55` AND `carbs_g ≤ 45g/portion`.

### with `nova-qa-elite`

| What I request | Why | Acceptance |
|----------------|-----|-----------|
| Golden set of 30 user profiles | regression CI for every algorithm change | profiles cover: athlete bulker, sedentary obese, diabetes_t2 + LatAm, vegan 22F, pregnant trim2, CKD stage 3, elderly 78M underweight, lactating, hypertensive 65F LatAm high-sodium baseline, plateau detected 28d deficit. Each profile shipped as JSON fixture. |
| Property-based tests on BMR/TDEE/macros | catch boundary bugs | `hypothesis` strategies for valid biometrics ranges |
| Plan-level invariants | catch L1→L4 leaks | (a) no recipe in plan has user-allergen overlap, (b) no contraindicated condition served, (c) daily kcal within ±5% target, (d) daily protein within ±10g target, (e) no recipe repeats <4 days |
| Adherence calibration metric | adherence prediction must be honest | Brier ≤ 0.20 against real food_log completion data (post-launch month 2) |
| kcal trajectory MAE | recalibration loop correctness | mean abs error ≤ 300 kcal/week vs observed weight change, measured per cohort |

### with `nova-nutrition-backend-architect`

Escalate to architect when:
- New DB columns needed (every new catalog field in §2 → migration).
- New table (e.g. `plan_warnings`, `recalibration_history` for audit trail).
- pgvector index tuning (HNSW params) when L3 latency p95 > 300ms.
- Read-replica routing for plan generation (when concurrent plan-gen > 100 RPS).
- Event-sourcing of `RecalibrationApplied` / `PlateauDetected` (currently fire-and-forget).

---

## 4. Pre-prod checklist — algorithm owner's responsibility

Verifiable items before exposing `POST /plans` to real users.

### 4.1 Smoke tests (must pass in CI)

- [ ] `compute_bmr` matches Mifflin reference table (10 known cases, ±1 kcal).
- [ ] `compute_tdee` × 5 activity factors returns expected within ±1.
- [ ] `compute_macros` for `(2000 kcal, 80 kg, weight_loss)` → `(144, 188, 56)` ±2g, derived kcal within `MACRO_TOLERANCE`.
- [ ] `recalibrate` with 14d plateau series + 14d intake → `RecalibrationResult` reason='plateau', tdee clamped ±15%.
- [ ] `create_plan` end-to-end happy path for LatAm omnivore weight_loss → returns 7-day plan with no L1/L2/L4 errors.
- [ ] Allergen leak test: user `allergies=[tree_nuts]` → 1000 plan generations, 0 recipes containing tree-nut ingredients in `ingredients[]` (defensive regex).
- [ ] Diabetes refusal: user `conditions=[diabetes_t2]` → use case returns `precondition_failed: diabetes_module_pending`.
- [ ] US refusal: user `region=us` → use case returns `precondition_failed: region_not_supported`.
- [ ] Snack refusal: `meals_per_day=4` → `precondition_failed: snack_catalog_pending`.

### 4.2 Golden set (built with QA)

30 profiles covering edge cases:

| # | Profile | Critical assertion |
|---|---------|--------------------|
| 1–3 | Sedentary M/F/X 25-35 LatAm, weight_loss | kcal 1500–1900, no contraindications |
| 4–6 | Athlete M bodyfat 10%, muscle_gain | BMR warning emitted; protein ≥1.8 g/kg; kcal ≥3200 |
| 7–9 | Obese BMI 35, weight_loss aggressive | kcal ≥ BMR × 1.0 floor enforced; protein capped 180g |
| 10 | Diabetes_t2 LatAm M 55 | **refused** with `diabetes_module_pending` |
| 11 | Pregnancy trim2 F 30 | **refused** with `pregnancy_module_pending` |
| 12 | CKD stage 3 M 60 | **refused** with `ckd_module_pending` |
| 13–14 | Vegan F 28, omnivore default | plan generated; B12 warning |
| 15 | Elderly M 78 underweight | weight_gain target; kcal +500 surplus capped |
| 16 | Lactating F 32 | **refused** with `lactation_module_pending` |
| 17 | Hypertension M 50 LatAm | sodium gate active; plan kept |
| 18 | Hypercholesterolemia F 45 | sat_fat gate active |
| 19 | Gout M 55 | organ_meat/shellfish excluded |
| 20 | Plateau detected 21d | recalibration triggered; tdee adjusted; rationale mentions plateau |
| 21 | Tree-nut allergy F 22 | 100% recipes free of tree-nut ingredient strings |
| 22 | Gluten allergy M 30 (celiac) | 100% gluten-free |
| 23 | Vegetarian goal=health F 40 | macros respect goal defaults |
| 24 | US region M 30 | **refused** with `region_not_supported` |
| 25 | Missing bodyfat athlete-tagged | Mifflin used + `warnings[].bmr_underestimate_possible` |
| 26 | Missing weight_logs | recalibration skipped='insufficient_data' |
| 27 | Insufficient food_logs | taste EMA fallback; cultural defaults |
| 28 | High prep-time preference (60min) | L3 prep_fit ranks longer recipes higher |
| 29 | Wearable-connected high activity | (deferred) static factor used, warning emitted |
| 30 | Cooldown active (recalibrated 5d ago) | recalibration skipped='cooldown' |

### 4.3 Quality metrics — go/no-go thresholds

| Metric | Target | Measure |
|--------|-------:|---------|
| Macro accuracy: `|derived_kcal − target_kcal| / target_kcal` per plan day | **≤ 5%** | mean across golden set |
| Allergen safety: recipes with user-allergen overlap served | **0 / 1M plan generations** | property test ×1M |
| Contraindication safety: contraindicated-condition recipes served | **0 / 1M** | property test ×1M |
| Plan generation p95 latency | **≤ 1.5 s** | load test 50 RPS |
| Recalibration false-positive rate (synthetic stable cohort) | **≤ 10%** | backtest |
| Adherence prediction Brier score | placeholder 0.70 constant (low confidence flag) | n/a v1 |
| kcal trajectory MAE | not measurable pre-launch | post-launch month 2 |

### 4.4 Edge cases that crash today (must be handled)

- Age 0, age 200 → ValueError at VO layer (verify).
- Weight 0, weight 500 → VO layer.
- Sex 'other' / 'X' → currently raises in `compute_bmr` ("unknown sex"). Decision needed: default to female formula (more conservative) or refuse. **Decision: default female-formula + warning. Document.**
- Empty weight_logs → recalibration returns `insufficient_data` (verified).
- All weights identical → OLS slope 0, plateau path. OK.
- `kcal_target=0` after extreme deficit clamp → `KcalRange` raises; clamp at `BMR × 1.0` upstream.
- `bodyfat_pct > 1.0` (user entered 25 not 0.25) → input validation needed.
- `conditions = [diabetes_t1, diabetes_t2]` simultaneous → take the stricter (t1) gates.
- Timezone-naive `weight_logs` timestamps mixed with aware → recalibration crash. Verify all VOs are tz-aware.

---

## 5. Post-launch upgrade roadmap

### Phase 1 — 0 to 100 users (month 1)

Goal: prove plan generation doesn't kill, mislead, or bore users. Minimum viable algorithms.

| Item | Owner | Effort |
|------|-------|--------|
| Ship items P0 from §1 (#4, #5, #8, #15, #16, #17 + defensive scan) | algo + clinical | 20h algo + catalog work |
| Wire `warnings[]` and `uses_data[]` into plan output JSON | algo | 4h |
| Persist recalibration history table | architect | 4h |
| Adherence telemetry (which recipes get swapped/skipped) | architect | 4h |
| Manual review of first 50 generated plans by clinical | clinical | n/a |

**Exit criterion:** 100 users for ≥14 days with 0 P0/P1 incidents, allergen-safety property tests still green.

### Phase 2 — 100 to 1000 users (months 2–3)

Goal: observable algorithm upgrades, data starts flowing back.

| Item | Owner | Effort | Trigger |
|------|-------|--------|---------|
| Cunningham/Katch-McArdle BMR switch | algo | 4h | ≥10 athlete complaints "kcal too low" |
| LBM-anchored protein | algo | 3h | ≥30 obese users with macro complaints |
| kcal CI from intake variance | algo | 3h | once ≥30 users have 14d food_logs |
| Diabetes module activation (algo unblocks once catalog GI shipped) | algo + clinical | 6h algo, 80h catalog | catalog ships GI for ≥95% recipes |
| Pregnancy + lactation modules | algo + clinical | 12h algo, 60h catalog | catalog ships ≥15 recipes per trimester |
| CKD module | algo + clinical | 10h algo, 40h catalog | catalog ships K, P, Na for ≥90% |
| Real adherence prediction (logistic on streak + swap rate) | algo + QA | 8h | ≥4 weeks of food_log data per user cohort |
| Snack catalog + 4-meal plans | clinical + algo | 1h algo, 150h catalog | catalog ships ≥300 snacks |
| US region launch | clinical + algo | 0h algo, weeks catalog | catalog ships US recipes |
| Plateau visualisation in plan output | algo + frontend | 6h | demand |

**Exit criterion:** Brier ≤ 0.25 on adherence prediction, kcal trajectory MAE ≤ 400 kcal/week.

### Phase 3 — 1k to 10k users (months 4–9)

Goal: research-grade algorithms, defensible product.

| Item | Owner | Effort |
|------|-------|--------|
| Kalman filter for weight smoothing | algo | 8h |
| PELT change-point detection for plateau | algo | 6h |
| NSGA-II Pareto L3 ranking | algo | 12h |
| Hall NIDDK two-compartment body model | algo | 20h |
| Multi-armed bandit for L3 weight tuning | algo | 16h |
| Micronutrient bioavailability (iron heme, calcium, zinc, omega-3) | algo + clinical | 12h algo, 80h catalog |
| Forbes partitioning in expected-outcome reporting | algo | 3h |
| Variety penalty via embedding cosine to 14d centroid | algo | 4h |
| Wearable integration (Apple Health, Google Fit) for dynamic TDEE | algo + integrations | 24h |
| Embedding-based variety + semantic dedupe | algo | 6h |

**Exit criterion:** Brier ≤ 0.20, kcal MAE ≤ 300 kcal/week, p95 plan latency ≤ 1.0s at 200 RPS.

---

## 6. Decisions captured

1. **Adaptive thermogenesis (#2)** is folded into the 14d recalibration cycle for v1. Explicit `days_in_deficit` correction deferred.
2. **Diabetes / pregnancy / lactation / CKD plans** are refused at signup with module-pending message. **No degraded plans for these populations.**
3. **US region** refused at signup until catalog ships.
4. **Snacks** disabled (`meals_per_day=4` refused) until catalog ships.
5. **Tree-nut defensive ingredient scan** added in L1 as belt-and-braces — runs even after catalog allergen fix.
6. **Embeddings** must be backfilled before launch (option a, ~$0.40, 30 min) rather than reweighting L3 (option b).
7. **Sex 'other'** uses female-formula BMR (conservative) + warning. Documented.
8. **Recalibration history** persisted from day 1 for post-launch audit.
9. **Adherence prediction** ships as constant 0.70 with `confidence: low`; replaced phase 2.
10. **kcal range CI** stays ±100 v1; widens to intake-variance based phase 2.

---

## 7. Cited primary literature

- Mifflin MD et al. (1990) — Am J Clin Nutr. BMR predictive equation.
- Hall KD (2010) — Am J Physiol. Multi-organ metabolic model (phase 3 reference).
- Trexler ET, Smith-Ryan AE, Norton LE (2014) — JISSN. Metabolic adaptation to weight loss (justifies adaptive correction, folded into recalibration v1).
- Forbes GB (1987) — Nutr Rev. LBM-body fat interrelationships (phase 3 partitioning).
- Phillips SM, van Loon LJ (2011) — J Sports Sci. Dietary protein for athletes (justifies LBM-anchored protein).

---

## 8. Owner action list (sleep-on-it priorities)

1. **Block diabetes, pregnancy, lactation, CKD, and US signups** at the API gateway before any external traffic. One config flag. ~1h.
2. **Confirm tree-nut catalog fix has shipped and verified** before launch; add the defensive ingredient regex in L1 as a parallel guard. ~1h.
3. **Backfill embeddings** for the 2000 recipes (`text-embedding-3-small`, ~$0.40, 30 min). Without this, L3 ranking is 40% noise.
