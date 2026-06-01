# NOVA Plan Algorithm — Master Plan (Elite Team Synthesis)

**Date:** 2026-06-01
**Authors:** 6 NOVA team agents — algorithms / clinical / backend-architect / design-patterns / qa-elite / api-expert
**Status:** Source of truth for plan-generation algorithm evolution. Supersedes ad-hoc decisions.

---

## TL;DR

The plan-generation pipeline is **the moat**. It will win against Fitia / MyFitnessPal / Lifesum / Yazio on three axes competitors cannot match cheaply: (1) **adaptive thermogenesis + observed-TDEE recalibration**, (2) **condition-aware ranking at generation time** (not post-filter), (3) **variety + adherence forecasting**. Everything below protects those three differentiators from regressing as users grow from 100 → 100k and catalog from 2k → 50k recipes.

**3 ship horizons, 5 critical scaling risks, 1 strict architectural invariant: the algorithm must be evolvable without breaking mobile clients or producing harmful plans.**

---

## Horizon 1 — Ship narrow MVP safely (next 30 days)

Goal: LatAm omnivore, 3 goals, no clinical conditions. Already gated (Option A shipped). Algorithm fixes that unblock real shipping.

### Algorithm

| # | Item | Why | Effort |
|---|------|-----|--------|
| H1.1 | **Macro back-adjust loop** — `carbs = (kcal − 4P − 9F)/4`, iterate ±1g until `|kcal_derived − target| ≤ 2%` | Plans leak 80-150 kcal/day silently → recalibration fights ghost error | S |
| H1.2 | **Protein anchored to LBM** — `P = k·LBM`, k∈{1.8 loss, 1.6 maintain, 2.0 surplus}, fallback `LBM = weight·0.82♂/0.75♀` | Athletes under-protein, obese over-protein | S |
| H1.3 | **Fat floor + goal fat-fraction** — `F ≥ 0.6·weight`, fat-pct {0.25 loss, 0.28 maint, 0.30 health} | Hormonal suppression under aggressive deficit | S |
| H1.4 | **kcal clamp with BMR safety floor** — refuse `kcal_target < BMR·0.9`; deficit cap `min(500, 0.25·TDEE)` | Unsafe deficits = lawsuit surface + metabolic damage | S |
| H1.5 | **Variety penalty (Jaccard until embeddings ready)** — `score_variety = 1 − Jaccard(candidate.tags ∪ ingredient_class, last_14d_set)` | Replaces dead 40% L3 cosine weight today | M |
| H1.6 | **Embedding backfill ($0.40)** — then swap Jaccard for cosine | Unlocks taste-aware ranking | S |

### Catalog patches (clinical-generator)

- 37 tree-nut tagging fixes (append `tree_nuts` to `allergens[]`, no removal).
- 87 high-carb diabetes_t2: strip `recommendedForConditions: diabetes_t2`, don't contraindicate.
- Schema migration: add `gi`, `gl`, `potassium_mg`, `phosphorus_mg`, `iron_mg`, `heme_pct`, `calcium_mg`, `omega3_mg`, `folate_ug`, `fiber_g`, `sodium_mg` columns. Backfill only the ~600 conditions-tagged recipes; rest stay NULL.

### Architecture / patterns

- **Pipeline pattern** — formalize `Stage` Protocol + immutable `PlanGenContext` (frozen dataclass) + per-stage budget. Pure composition, no orchestration logic in `Pipeline.run`.
- **Anti-coupling** — define `TasteProfileReader` Protocol in `app/plan/domain/ports.py`; tracking implements it. Plan never imports tracking domain.
- **Import-linter contract** — CI rule: `app.plan.* ⊬ app.tracking.domain.*`.
- **Decimal-only domain** — flake8 plugin flagging `float()` in domain.

### QA gates (must land H1)

- Property invariants live (10 listed below).
- Mutation testing `mutmut` on Layer1 + Layer4 ≥ 90% kill rate.
- p95 plan-gen < 800ms enforced in CI via pytest-benchmark.
- Golden set 40 user profiles, nightly run, deploy block if `golden_pass_rate` drops >5pp.

### API

- `POST /v1/plan/generate` — `Idempotency-Key` mandatory, `Prefer: respond-async` supported, 201 sync vs 202 + job_id async.
- `algorithm_version` field in every plan response.
- Recipe snapshot embedded (immutable) — protects history when catalog mutates.

---

## Horizon 2 — Clinical expansion + US (30-90 days)

Unlocks: diabetes_t2 / hypertension / CKD / pregnancy / lactation / US region (the 6 segments gated today via `MVP_SEGMENT_GATE_ENABLED`).

### Algorithm

| # | Item | Formula sketch | Catalog dep |
|---|------|----------------|-------------|
| H2.1 | **Glycemic Load gate** | `GL = (GI·carbs)/100`; cap daily GL ≤80, per-meal ≤30 (diabetes) | `recipes.gi` (USDA/Intl GI tables, fallback by carb class) |
| H2.2 | **CKD electrolyte cap** | `K ≤ 2000mg`, `P_kcal ≤ 800mg`, `protein ≤ 0.8·weight`, `Na ≤ 1500mg` | `potassium_mg`, `phosphorus_mg` |
| H2.3 | **Hypertension DASH score** | DASH ≥ 0.7, daily Na ≤ 1500, K ≥ 4700 | `food_group_dash` enum + existing sodium_mg |
| H2.4 | **Pregnancy/lactation** | kcal `+0/+340/+452/+500` per stage; folate ≥600µg, iron ≥27mg, Ca ≥1000mg; exclude raw fish, soft cheese, high-Hg | `folate_ug`, `iron_mg`, `pregnancy_safe BOOL` |
| H2.5 | **US region** | Imperial UoM display, Na baseline 1500 hard, FDC nutrient mapping | `recipes.regions[] ∋ us` + US-specific recipes |

### Patterns (Strategy + Registry)

Replace L1 `if "diabetes_t2" in conditions:` chain with `ConditionGate` Protocol + registry:

```python
class ConditionGate(Protocol):
    condition: str
    def contribute(self, q: RecipeQuery) -> RecipeQuery: ...

CONDITION_GATES: dict[str, list[ConditionGate]] = {}
def register(gate): CONDITION_GATES.setdefault(gate.condition, []).append(gate)
```

Open/Closed: new condition = new class + `register(...)`. Layer1 never edited.

### Catalog growth (clinical-generator)

200 recipes/week sustainable. 5-gate INSERT-blocking validator:
1. Macro math `|kcal − (4P + 4C + 9F)| ≤ 2%`.
2. Allergen regex scan vs `allergens[]` (the audit gap).
3. Clinical recommend gate: `recommendedForConditions` requires all micronutrient gates green.
4. Region-plausibility.
5. Naming uniqueness (embed cosine < 0.92 within `(meal_time, region, dietary_pattern)`).

Pareto fill: snacks×latam×3 missing goals → vegan×5 regions → DASH/hypertension → ketogenic → low-FODMAP.

Minimum recipe count per condition unlock:
- hypertension/DASH: 300
- diabetes_t2: 400
- ckd: 200
- pregnancy: 250
- lactation: 150

### Backend / scale

- **Postgres indexes (now)**: GIN on `regions`, `allergens`, `contraindicated_conditions`, `tags`, `target_goals`. Composite `(meal_time, kcal_per_serving) WHERE deleted_at IS NULL`. HNSW `(m=32, ef_construction=200)` on embedding.
- **Eligibility cache** — Redis key = `hash(region, allergens, conditions, meal_time, goal)`, TTL 24h. Idempotent: invalidate on catalog upsert event.
- **Plan immutability** — `plan_versions` table jsonb snapshot + `algo_version`. Never mutate.
- **Outbox table** — dispatch `PlanRecalibrated` to clinical-audit queue (compliance).

### API

- `POST /v1/plan/me/recalibrate` returns **202** + `diff_preview_url` + 24h acceptance window.
- RFC 7807 problem types: `urn:nova:problem:plan:{segment-unsupported-mvp, generation-failed, no-eligible-recipes, cost-cap-exceeded, plateau-detection-pending, recalibration-in-flight, profile-incomplete}`.
- Region: **header `X-Region`** (default from JWT). Rejected: path-based routing (breaks codegen).

---

## Horizon 3 — Moat (90-365 days)

Order by ROI/effort. Each one is a competitor-defensive differentiator.

| # | Item | Formula | Effort | Beats |
|---|------|---------|--------|-------|
| H3.1 | **Adaptive thermogenesis + observed-TDEE recalibration** | `TDEE_obs = mean(kcal_in_14d) − slope·7700`; `TDEE_new = 0.5·Mifflin + 0.5·TDEE_obs`, clamp ±15%; deficit-fatigue correction `×(1 − 0.07·log(days_deficit/14))` after 14d | M | All competitors (static TDEE) |
| H3.2 | **Plateau detection (Kalman + OLS CI + PELT)** | Kalman smooth weight; OLS slope 95% CI on 14d window; plateau iff `0 ∈ CI`; PELT change-point 30d for regime shift | M | All competitors (manual recompute) |
| H3.3 | **Adherence forecasting (logistic)** | `P(adhere) = σ(β₀ + β₁·streak + β₂·(1−swap_rate) + β₃·completion_14d + β₄·variety)` trained nightly per user | M | All (proactive intervention) |
| H3.4 | **Pareto multi-objective (NSGA-II)** | Minimise `(macro_err, prep_time, cost, variety_loss, cultural_misfit)`; expose 3 frontier picks per slot | L | Fitia (greedy single-axis) |
| H3.5 | **Micronutrient bioavailability** | iron `heme·0.25 + non_heme·0.08·(1+vitC/40)`; Ca `dairy·0.30 + low_oxalate_leafy·0.25 + spinach·0.05`; Zn `(Zn·0.30)·(1−0.5·phytate)` | L | Yazio/Lifesum (RDA face-value) |
| H3.6 | **Forbes lean/fat partition prediction** | `fat_loss_frac = 1/(1 + 10.4/FM_kg)` → predict body comp trajectory, not just weight | S | All (weight-only forecasts) |

### Backend at H3 tier

- Catalog 10k+ → IVFFlat fallback (lists≈√N) when HNSW RAM exceeds 600MB.
- LIST partitioning on `recipes` by `region` once 3+ regions live.
- Pre-compute "tomorrow's plan" overnight via Arq cron (tz-staggered, 02:00–06:00). Morning fetch = single SELECT <20ms.
- Saga for recalibration: `DetectPlateau → RecomputeTDEE → RegeneratePlan → NotifyUser`, with compensations + idempotency key (`hash(user_id, plateau_window_end)`).

### Patterns at H3 tier

- **Strategy + Registry** for ranking signals — each signal a class implementing `RankingSignal` Protocol; weights live in `plan_weight_vectors` table (variant_id PK) → A/B + Thompson bandit ready without code change.
- **Audit attribution** — plan persists `(plan_id, variant_id, weights_checksum)` so we can attribute outcomes to weight sets.
- **CQRS on read side only** — `plan_read_models` denormalized view for mobile (meals + macros + swaps + acceptance state). Write side stays normalized.

---

## 5 Critical Scaling Risks (architect out preventively)

| # | Risk | Trigger | Counter |
|---|------|---------|---------|
| **R1** | **Catalog nutrient sparsity blocks condition stacking** | User with diabetes+CKD+hypertension+celiac+vegan finds <5 eligible recipes; plan-gen returns empty/infinite-loop | (a) CI gate: PR rejected if new recipe has NULL in clinical-relevant cols. (b) Pre-flight feasibility check before generation; if `min_slot_eligible < 7`, surface "constraints require manual catalog expansion" and queue to clinical-generator. Never silently degrade. |
| **R2** | **Plan-gen latency collapse at scale** | NSGA-II + Kalman + Pareto at 1500 concurrent users on 2vCPU | (a) Pre-compute overnight via Arq. (b) Eligibility-set Redis cache `hash(region, conditions, allergens)`. (c) Per-layer budget enforce (50/100/300/100ms). (d) Bound L2 shortlist ≤80 candidates. |
| **R3** | **Recalibration oscillation under noisy weight logs** | Without Kalman + cooldown, TDEE swings ±20% weekly → kcal_target jitter → user distrust | (a) Mandatory 14d cooldown. (b) Clamp `|ΔTDEE| ≤ 15%`. (c) Require `delta_ratio > 0.5` (ADR-0002 already enforces). (d) Audit log every recalibration with before/after + trigger. |
| **R4** | **Embedding drift as catalog grows** | New recipes from generator → new embedding space distribution → cosine scores incomparable to historical user EMA | (a) Version embeddings (`embedding_v INT`). (b) Recompute user `taste_vector` when version bumps. (c) A/B gate on rollout. (d) Same versioning for GI/micros coefficient tables. |
| **R5** | **Outbox / audit lag → clinical liability gap** | Recalibration event not dispatched to compliance queue within SLO | Outbox + dead-letter + lag SLO alert (>5min). Plan stored before event emit; reconciliation job daily. |

---

## 10 Invariants (must always hold — property tests)

1. **AllergenExclusion**: `∀ meal: meal.allergens ∩ user.allergies = ∅`
2. **MacroConsistency**: `|kcal − (4P + 4C + 9F)| / kcal ≤ 0.02` per meal AND per day
3. **KcalTargetBand**: `|Σ kcal − target| / target ≤ 0.05`
4. **GoalDirectionality**: `weight_loss ⇒ Σ kcal ≤ TDEE − 250`; `weight_gain ⇒ ≥ TDEE + 200`
5. **ConditionSafety (diabetes_t2)**: `∀ meal: carbs ≤ 60 ∧ sugar ≤ 15` (until GL gate ships)
6. **Variety7d**: `∀ recipe r: count(r in 7d plan) ≤ 2`
7. **MacroSplitInBand**: `protein_pct ∈ [target ± 5%]` (same carbs/fat)
8. **SlotCoverage**: `{breakfast, lunch, dinner} ⊆ plan.slots`
9. **DeterminismGivenSeed**: `generate(user, catalog, seed=42)` byte-equal across runs
10. **MicroFloor**: fiber ≥ 25g/day, sodium ≤ 2300mg, iron ≥ DRI(sex,age)

All implemented via `hypothesis` strategies for `user_profile_strategy()` + `catalog_strategy()`. 200 examples per property minimum.

---

## 10 Critical-Failure Detectors (prod metrics)

| # | Signal | Threshold | Action |
|---|--------|-----------|--------|
| 1 | `allergen_leak_total` | > 0 ever | PagerDuty P1, kill-switch `plan_gen.enabled=false` |
| 2 | `condition_violation_total{condition,field}` | > 0/10k gens | Block recipe, alert |
| 3 | `macro_inconsistency_pct` per plan | p99 > 5% | Warn, weekly review |
| 4 | TDEE prediction error (predicted vs actual Δweight) | MAE > 25% / 14d cohort | Recalibration audit |
| 5 | Recipe Gini across users | > 0.7 | Variety alarm |
| 6 | Cold-start golden subset pass | drop > 15% vs warm | Block deploy |
| 7 | Plan-gen p95 latency | > 800ms / 5m | Auto-rollback last catalog patch |
| 8 | Plateau-not-recalibrated rate | > 10% stalled users | Recalibration job audit |
| 9 | Locale field mismatch | > 0.1% | Block i18n deploy |
| 10 | Catalog near-dup ratio (cosine > 0.95) | > 5% growth/week | Curator review queue |

---

## Cost ceiling

At 10k MAU on Hostinger 8GB/2vCPU:

| Item | Calc | $/mo |
|------|------|------|
| Embeddings (text-embedding-3-small, delta 5%/mo) | 50k × 0.05 × 200 tok × $0.02/1M | $0.01 |
| GPT-4o-mini coach (50k tok/user/mo cap) | $0.006/user × 10k | $60 |
| Postgres storage | included | $0 |
| VPS Hostinger | flat | $20 |
| **Total** | | **~$80 = $0.008/user/mo** |

Hard cap per user/day enforced pre-call (ADR-0004): $0.02/user/day.

Headroom: x10 users before VPS migration to dedicated (Hetzner AX41 ~$50).

---

## Files to create (Horizon 1 + 2 prep)

```
app/plan/domain/ports.py                — TasteProfileReader, WeightVectorRepo, Solver,
                                          Constraint, ConditionGate, RankingSignal, Stage
app/plan/domain/context.py              — frozen PlanGenContext, StageTrace
app/plan/domain/condition_gates/        — one file per condition
app/plan/domain/ranking_signals/        — one file per signal
app/plan/domain/constraints.py          — DailyKcalEnvelope, MacroEnvelope, etc.
app/plan/application/pipeline.py        — generic Pipeline.run
app/plan/application/recalibration_saga.py
app/tracking/infrastructure/plan_adapters.py — TrackingTasteProfileReader
app/shared/domain/macro_tolerance.py    — single tolerance constant
alembic/versions/xxxx_plan_weight_vectors.py — plan_weight_vectors, plan_versions,
                                               plan_recalibration_sagas, outbox
tests/plan/golden/profiles.yaml         — 40 golden profiles
tests/plan/regression/test_population.py — 1000 synthetic users population sim
ops/prometheus/plan_alerts.yml          — 10 critical-failure detectors
docs/ops/runbooks/plan-algorithm-incidents.md
docs/catalog/GROWTH_RUNBOOK.md          — clinical-generator playbook
```

---

## Decisions deferred (explicit YAGNI)

| Decision | Defer until |
|----------|-------------|
| ILP / OR-tools coherence solver | Greedy violation rate > 5% measured on real users |
| Qdrant / Pinecone migration | Catalog > 500k OR IVFFlat recall < 0.88 |
| Postgres read replicas | p95 CPU > 70% sustained |
| CDC (Debezium) | Multi-node, > 100k users |
| Multi-region active-active | Out of scope (single eu-central VPS) |
| SSE for live recalibration progress | Coach streaming needs same pattern first |
| Public webhooks | First partner integration request |

---

## Why this beats Fitia / MyFitnessPal / Lifesum / Yazio

| Axis | Competitors | NOVA |
|------|-------------|------|
| TDEE | Static Mifflin, manual user edit | Adaptive + observed kcal-in / weight-slope blend, auto-correct for adaptive thermogenesis |
| Conditions | Post-filter "low sodium" tag | Pre-generation gates per condition + clinical recommend audit trail |
| Variety | Template-driven, ~50 recipes recycle | Embedding cosine + Jaccard penalty + 7d hard limit + variety Gini metric |
| Recalibration | Manual recompute by user | Plateau detection (Kalman + PELT) + auto-saga + 24h accept/reject |
| Catalog growth | Manual curation, ~500-2k recipes total | LLM batch + 5-gate INSERT validator scaling 200/week safely |
| Audit | None or hidden | Immutable plan_versions + variant_id + weights_checksum |
| Cost ceiling | Unlimited LLM calls | ADR-0004 cost cap per-user-per-day enforced pre-call |

---

## Critical sequencing

1. **Catalog clinical patch** (37 + 87 fixes) — **gates everything**. Without this, can't lift segment gate.
2. **Schema migration** for micronutrients — **gates H2**. Without these columns, no GL / DASH / CKD / pregnancy gates.
3. **Pipeline pattern + Strategy** refactor — **gates H2 + H3**. Without it, adding conditions / signals = exponential `if` chains in Layer1.
4. **Property invariants + golden set** — **gates safe ship**. Without these, every change risks silent regression.
5. **Recalibration saga + plateau detection** — **gates moat**. Without these, NOVA = "another macro calculator."

Everything else is downstream of these 5.

---

## Owner action items

| Priority | Item | Agent |
|----------|------|-------|
| P0 | Catalog patch (37 tree-nut + 87 diabetes_t2) | nova-clinical-nutrition-generator |
| P0 | Schema migration micronutrients + backfill 600 conditions-tagged | nova-nutrition-backend-architect |
| P0 | Embedding backfill ($0.40 / 30min) | owner runs script |
| P1 | Pipeline / Strategy refactor (H1 patterns) | nova-design-patterns-expert |
| P1 | Property invariants + golden set | nova-qa-elite |
| P1 | Plan_versions + outbox tables | nova-nutrition-backend-architect |
| P2 | API contract finalization (idempotency, 7807, X-Region) | nova-api-expert |
| P2 | H1 algorithm fixes (back-adjust, LBM protein, BMR clamp) | nova-nutrition-algorithms-expert |
| P3 | H2 condition gates (diabetes_t2 / hypertension / CKD) | nova-nutrition-algorithms-expert + nova-clinical-nutrition-generator |
| P3 | Recalibration saga + plateau detection | nova-nutrition-algorithms-expert + nova-design-patterns-expert |

---

## End

This document is the single source of truth for plan-algorithm direction. Update via ADRs (`docs/adr/`) when decisions diverge.
