# NOVA Nutrition — Pre-Implementation QA Review

- Date: 2026-05-30
- Reviewer: `nova-qa-elite`
- Scope: backend design spec, seed catalog, architect agent files
- Artifacts reviewed:
  - `docs/superpowers/specs/2026-05-30-nova-backend-design.md`
  - `data/meals/nova_meals_catalog.json` (2000 records, programmatic audit)
  - `.claude/agents/nova-backend-architect.md`
  - `.claude/agents/nova-nutrition-backend-architect.md`
  - `.claude/agents/nova-clinical-nutrition-generator.md`
  - `.claude/agents/nova-qa-elite.md` (mandate, self)

---

## Verdict

**REQUEST_CHANGES** (with several `BLOCK`-level findings on data quality and nutrition safety that must be resolved before implementation begins).

The spec is internally coherent, decisions are locked, and the layering is sound. Three classes of problems prevent approval:
1. Catalog data is **not safe to ship** as-is (allergen and contraindication false negatives; allergen-as-condition leakage; uncontrolled condition vocabulary).
2. Schema/spec/catalog **disagree on enums** (meal time, allergen taxonomy, condition vocabulary, language of identifiers).
3. The spec defers or omits multiple **operational invariants** my mandate requires before code is written (idempotency keys, secret rotation, kill-switches, OpenAI cost cap, GDPR delete path, golden sets, prompt versioning).

---

## Risk Score

| Dimension | Score (0–5) | Justification |
|---|---:|---|
| nutrition  | **4** | Catalog has 144 recipes with purine-rich ingredients lacking `gout`, 161 dairy false-negatives, 169 gluten false-negatives, 22 unknown allergens (`sesame`, `mustard`). Allergy hard-exclude (spec §9.5, QA suite §2) will silently fail on real data. |
| security  | **3** | Auth design fine on paper but missing: refresh-token reuse detection family-revoke, JWT `kid`/JWKS rotation procedure, OTP brute-force lockout policy, audit-log row-level revoke DDL, EXIF strip verification harness, secrets rotation runbook, GDPR/LGPD right-to-erasure. PII at rest mentioned (`pgcrypto`) but no key-management story. |
| perf      | **2** | SLOs stated (§13) but no per-endpoint budget, no N+1 detector, no k6 baselines committed. Vision job 8s is loose without retry budget. HNSW index has no `m`/`ef_construction` tuning. |
| data      | **5** | Macro math is perfect (0/2000 fails — credit where due) but every other data-quality dimension fails: enum drift, allergen-as-condition pollution, near-duplicate condition labels (`peanut_allergy` ⟂ `peanuts_allergy`), zero `snack` records, no `fiber/sugar/sodium/sat_fat` fields, only one placeholder image URL, no embeddings, no `nombre_norm`, no `country`. |
| rollback  | **3** | Alembic + downgrade mentioned (§14) but no expand-contract example, no feature-flag framework, no kill-switch for AI features, no prompt versioning table. |

---

## Findings

### #1 BLOCK — Catalog allergen taxonomy is open, not closed
- Evidence: `data/meals/nova_meals_catalog.json` contains allergens `sesame` (22 records) and `mustard` (1 record) which are **not in** the agent-defined closed enum `{dairy, gluten, tree_nuts, peanuts, shellfish, fish, egg, soy}` (see `nova-clinical-nutrition-generator.md:71`).
- Why it matters: QA suite §11 requires a closed allergen enum; spec §9.5 says "hard-exclude by allergies". An unknown allergen will be silently dropped by any `WHERE allergen = ANY($1)` filter, producing a false-negative exclusion. A user who selects `sesame` allergy from the UI (likely supported — sesame is a top-9 US allergen as of FALCPA 2023) will be served sesame-containing recipes.
- Suggested fix: lock allergen enum at the schema layer (`CREATE TYPE allergen_enum AS ENUM (...)`); add sesame to the canonical list (top-9 US); ingest pipeline must reject (not warn) unknown values; emit metric `catalog.ingest.unknown_allergen`.
- Failing test: `tests/integration/recipes/test_catalog_ingest.py::test_unknown_allergen_rejects_record` — load JSON with `allergen='mustard'`; assert ingest returns non-zero exit + record not inserted.

### #2 BLOCK — 161 dairy / 169 gluten / 144 purine false negatives in seed data
- Evidence (heuristic via ingredient grep, sample):
  - `nova_meal_b01_001` "Bowl de Avena Mediterránea con Higos y Almendras" contains `yogur` but `allergens` has no `dairy`.
  - `nova_meal_b01_019` "Bagel Integral con Salmón Ahumado y Queso Crema Ligero" contains salmón + queso, lacks both `gout` contraindication and `dairy` allergen.
  - `nova_meal_b08_024` "Curry Verde de Pescado Blanco" contains pasta/fideo cue, lacks `gluten`.
  - Purine-rich keywords without `gout`: `salmón` ×105, `atún` ×39, `anchoa` ×1.
- Why it matters: spec §9.5 "hard-exclude by allergies" and QA mandate "Allergen hard-exclude" pillar are violated at the data layer. A user with `alergias=['lacteos']` who logs into NOVA day-1 will be served `b01_001` because the catalog says it has no dairy.
- Suggested fix: pre-ingest gate — a curated `ingredient -> allergens[]` lookup table runs on every record and **overrides** the LLM-generated tags before insert. Reject the record (or auto-add) if mismatch.
- Failing test: `tests/data/test_catalog_nutrition_safety.py::test_no_known_allergen_in_ingredients_without_tag` — parametrised over the dairy/gluten/egg/soy/fish/shellfish/peanuts/tree_nuts/sesame keyword sets; mandatory CI gate.

### #3 BLOCK — Allergen labels leaking into `recommendedForConditions` / `contraindicatedConditions`
- Evidence: 26 records have `egg` (and others: `shellfish`, `fish`) appearing as a *condition*. Sample: `nova_meal_b01_002`, `b01_011`, `b01_013`, `b01_014`, `b01_020`.
- Why it matters: condition vocabulary is being polluted with allergen tokens. Any condition-based filter (spec QA suite §2 "Contraindication": `condiciones=['diabetes_t2']`) will be matched against records where the value is actually an allergen. Type confusion → wrong recommendations.
- Suggested fix: schema-level disjointness check `assert allergens ∩ conditions == ∅`; reject offending records on ingest.
- Failing test: `tests/data/test_catalog_taxonomy.py::test_allergen_and_condition_vocabularies_are_disjoint`.

### #4 BLOCK — Condition vocabulary is uncontrolled (62 distinct values, with semantic duplicates)
- Evidence: enumerated `CONDITIONS` from the audit includes both `peanut_allergy` and `peanuts_allergy`; `tree_nut_allergy` and `tree_nuts_allergy`; `cardiovascular_disease`, `cardiovascular_disease_prevention`, `cardiovascular_health`; `build_muscle`, `muscle_building`, `muscle_hypertrophy`; `general_health` and `general_wellness`; plus invented entries like `liver_detox`, `antioxidant_support`.
- Why it matters: the spec's profile schema (`condiciones_medicas text[]`) gives no enum constraint. The recipe-selection use case (§9.5 "filter by objective") will silently miss matches due to label drift. The UI cannot present a coherent picker. ICD-10/SNOMED-CT alignment is impossible later without a migration.
- Suggested fix: define `app/recipes/domain/conditions.py` with a single canonical enum (≤25 values, mapped to ICD-10 categories); add a translation table for legacy catalog values; ingest pipeline normalises or rejects.
- Failing test: `tests/data/test_catalog_taxonomy.py::test_conditions_are_in_canonical_enum`.

### #5 BLOCK — Catalog has zero `snack` records but spec mandates the enum value
- Evidence: spec §7 declares `tiempo enum('desayuno','almuerzo','cena','snack')` (line 159, line 126). Catalog mealtime distribution: `{breakfast: 600, lunch: 800, dinner: 600, snack: 0}`.
- Why it matters: spec §9.5 plan generation "filter by meal_time + tag prefs" combined with `comidas_por_dia` allowing snack slots → plans with snacks will be empty/crash. UI tab for snacks has no data.
- Suggested fix: either generate ≥300 snack records (target ~15% of corpus) or remove `snack` from the enum and from spec §9.3 plan logic. Pick one and commit.
- Failing test: `tests/data/test_catalog_coverage.py::test_every_meal_time_has_minimum_records` (param: min 100 per enum value).

### #6 BLOCK — Identifier-language schism between spec and catalog
- Evidence: spec §7 enums use Spanish (`desayuno`, `almuerzo`, `cena`, `snack`, `hombre`, `mujer`, `bajar`, `mantener`, `ganar_musculo`, `activo`); catalog uses English (`breakfast`, `lunch`, `dinner`, `weight_loss`, `build_muscle`). Spec §7 column names also Spanish (`peso_kg`, `talla_cm`, `condiciones_medicas`); generator agent §4 mandates **English snake_case for system identifiers**.
- Why it matters: every ingest of `nova_meals_catalog.json` will require a translation map. Bilingual identifiers are a recipe for subtle bugs (`'snack'` vs `'snack'` is the same; `'cena'` vs `'dinner'` is not). The spec is approved for implementation with this contradiction unresolved.
- Suggested fix: pick one language for system identifiers (recommendation: **English snake_case** to match catalog and reduce ASCII issues), rewrite spec §7 enums and column names accordingly, and write a one-shot Alembic data migration script for catalog → DB translation as an explicit artifact.
- Failing test: `tests/data/test_catalog_ingest.py::test_catalog_values_match_db_enums` — fails until alignment.

### #7 REQUEST_CHANGES — Catalog macros lack `fiber`, `sugar`, `sodium_mg`, `saturated_fat`
- Evidence: catalog records carry only `proteinG/carbsG/fatG`. Spec §7 `foods` table has `fibra, azucar, sodio_mg, grasa_sat`. Spec §9.5 "Contraindication" QA scenario (`diabetes_t2 → no recipe with azucar_g > N`) cannot run on this data.
- Why it matters: nutrition filtering by sugar/sodium/sat-fat (the entire diabetes/hypertension/CVD safety pillar) is undefined at the recipe level. Reverse-engineering from ingredients via USDA FDC is a separate workstream.
- Suggested fix: extend the catalog schema (additive fields, default null), backfill via USDA FDC lookup in a `scripts/enrich_catalog_micros.py` job, and gate plan generation for sensitive conditions until enrichment ≥ 95%.
- Failing test: `tests/data/test_catalog_completeness.py::test_diabetes_recipes_have_sugar_field`.

### #8 REQUEST_CHANGES — Macro-math invariant in spec (`±5%`) vs QA suite (`±10%`)
- Evidence: spec §6 says `kcal == p*4 + c*4 + g*9 ± 5%`; QA mandate §11 says `±10%`; nutrition generator agent says `±5 kcal` absolute. Three different tolerances.
- Why it matters: ambiguous invariant → tests inconsistent with the domain VO; downstream filtering uncertain. (Empirical: current catalog is exact, max deviation = 0 kcal, mean abs deviation = 0.00 — so any of the three passes, but the contradiction must be resolved before code is written.)
- Suggested fix: pick `±2%` for in-domain VO (it's already exact) and document why; QA suite §11 catalog audit uses the same constant.
- Failing test: `tests/unit/domain/test_macro_breakdown.py::test_invariant_constant_matches_audit_constant`.

### #9 REQUEST_CHANGES — `nutritional_goals` "exactly one current row" invariant is unindexed
- Evidence: spec §7 comment says "Exactly one row per user with vigente_hasta IS NULL"; no partial unique index defined (cf. `plans.one_active_plan` which *does* have one).
- Why it matters: race on `WeightLogged` → two concurrent recalibrations → two rows with `vigente_hasta IS NULL` → `GET /me/targets` returns nondeterministic row.
- Suggested fix: `CREATE UNIQUE INDEX one_current_goals ON nutritional_goals(user_id) WHERE vigente_hasta IS NULL;`
- Failing test: `tests/integration/nutrition/test_recalibration_concurrency.py::test_two_parallel_recalibrations_yield_one_current_row` (50 parallel workers, assert exactly 1 surviving NULL).

### #10 REQUEST_CHANGES — Recalibration formula is underspecified
- Evidence: spec §9.2 says `tdee_nuevo = blend(mifflin_recalc, energy_balance_inferred)` — `blend()` is undefined; threshold `|delta_ratio - 1| > 0.5` has no smoothing; `slope(weight)` algorithm unspecified (OLS? Theil-Sen? robust to outlier daily fluctuation?). Architect agent says "rolling 14-day window <50% expected delta" → different threshold (0.5 vs <0.5 ratio is inverted).
- Why it matters: recalibration is the headline nutrition differentiator. Two architects already disagree. Without a precise formula, property-based tests cannot exist.
- Suggested fix: lock formula as ADR-002: `tdee_new = 0.6 * mifflin_recalc + 0.4 * energy_balance_estimate` clamped to ±15% of previous, requires ≥10 weight points in 14d, slope via Theil-Sen estimator; energy balance estimate `tdee_eb = mean(kcal_in) - (slope_kg_per_day * 7700)`.
- Failing test: `tests/unit/domain/test_recalibration.py::test_blend_function_is_deterministic_and_bounded` + property test `|tdee_new - tdee_prev| <= 0.15 * tdee_prev`.

### #11 REQUEST_CHANGES — Vision pipeline: no idempotency key, no dedup of duplicate uploads
- Evidence: spec §9.1 step 1–4 returns `202 {jobId}` but no `Idempotency-Key` header semantics. A retried POST after network loss creates a second job and a second food_log.
- Why it matters: mobile networks drop. Double-logging a meal corrupts daily kcal and recalibration.
- Suggested fix: require `Idempotency-Key` header on `POST /logs/food/photo`, `POST /logs/food`, `POST /logs/water`, `POST /logs/weight`, `POST /plans`. Store hash for 24h. Return original 202 on replay.
- Failing test: `tests/integration/tracking/test_idempotency.py::test_replay_returns_same_job_id`.

### #12 REQUEST_CHANGES — `match if confianza > 0.7` is a magic number with no calibration evidence
- Evidence: spec §9.1: "Match if confianza > 0.7"; QA mandate §3 requires `Brier score ≤ 0.20` and a reliability diagram.
- Why it matters: threshold dictates whether food_log is auto-attached or stored as free-text; wrong calibration → silent macro errors at scale.
- Suggested fix: ADR-003: threshold derived from golden-set calibration (precision ≥ 0.90 at chosen recall); committed reliability diagram in `docs/qa/vision-calibration/<date>.png`; threshold value in a single config constant.
- Failing test: `tests/ai/test_vision_calibration.py::test_threshold_meets_precision_floor`.

### #13 REQUEST_CHANGES — No prompt-versioning table or AI feature kill-switch
- Evidence: spec §9.4 coach SSE references "system prompt" but spec has no `ai_prompts(id, name, version, content, sha256, created_at, active)` table; no feature flag store; QA mandate "kill-switch test" requirement cannot be satisfied.
- Why it matters: prompt regressions cannot be A/B tested, rolled back, or attributed in incident postmortems. Vision/coach must be disable-able without a deploy.
- Suggested fix: add `ai_prompts` table + `feature_flags` table (or use Redis-backed Flagsmith-lite); every OpenAI call records `prompt_sha256` in `coach_messages` / `food_logs`.
- Failing test: `tests/integration/coach/test_prompt_version_recorded.py` + `tests/integration/feature_flags/test_kill_switch_blocks_vision.py`.

### #14 REQUEST_CHANGES — No per-user OpenAI cost cap
- Evidence: spec §19 "Decide cost cap policy" is an open follow-up. Spec is approved for implementation without it.
- Why it matters: a single user spamming `/coach/chat` or `POST /logs/food/photo` (5/min × 1440 = 7200 vision calls/day at $0.01+ each) can produce a five-figure bill in 24h. Rate limit (60/min) is per-minute, not per-day.
- Suggested fix: token budget per user/day in Redis sorted set; 402 (or graceful 429 with `Retry-After: <seconds_until_midnight>`) on exceed; alarm at 80%. Numbers committed in ADR-004.
- Failing test: `tests/integration/coach/test_daily_token_cap.py::test_cap_blocks_request_with_402`.

### #15 REQUEST_CHANGES — Refresh-token family-revoke (stolen-token detection) absent from spec
- Evidence: spec §7 `refresh_tokens(id, user_id, token_hash, expires_at, revoked_at)` — no `parent_id` / `family_id`. QA mandate §6 requires "stolen-token detection (parent token reuse → revoke entire family)".
- Why it matters: standard OAuth2 best-practice missing. A leaked refresh token grants persistent access.
- Suggested fix: add `family_id uuid, parent_id uuid`. On reuse of a revoked token, revoke entire `family_id`.
- Failing test: `tests/integration/identity/test_refresh_rotation.py::test_reused_token_revokes_family`.

### #16 REQUEST_CHANGES — No GDPR/LGPD `DELETE /me` data-erasure plan
- Evidence: spec has no §"Right to be forgotten". Mexican LFPDPPP, Brazilian LGPD, EU GDPR (if any EU user) all require it. `food_logs`, `weight_logs`, `coach_messages` contain health data.
- Why it matters: regulatory blocker for prod. Hypertable retention + audit-log immutability creates a tension that must be designed for explicitly.
- Suggested fix: ADR-005: hard-delete user PII; pseudonymise (replace `user_id` with `deleted_<uuid>`) in `audit_log` and `coach_messages` for analytics. Soft-delete tombstone with 30-day window per LFPDPPP.
- Failing test: `tests/integration/identity/test_user_erasure.py::test_delete_me_removes_all_pii_traces`.

### #17 REQUEST_CHANGES — Plan state machine missing illegal-transition guards
- Evidence: spec §7 `plans.estado enum('activo','completado','cancelado')` and §9.3 prose transitions, but no explicit transition table. QA mandate §1 requires `no illegal transition (e.g., completado → activo)`.
- Why it matters: domain invariant absent → no property-based test possible.
- Suggested fix: encode allowed transitions in `app/plan/domain/state.py`; DB-level CHECK via trigger or app-level guard with optimistic locking on version column.
- Failing test: `tests/unit/domain/plan/test_state_machine.py::test_illegal_transitions_raise`.

### #18 REQUEST_CHANGES — No EXIF strip verification harness
- Evidence: spec §10 says strip EXIF; §12 reiterates. QA mandate §8: "upload image with GPS tags → fetched URL has no `GPS*` tags". Image storage backend is deferred (spec §2, §18), so the strip happens but the *fetched URL contract* is undefined.
- Why it matters: GPS leak = location-of-home disclosure for every food photo. Test cannot exist until storage exists, but compress-and-discard-EXIF-on-write must be verified pre-storage.
- Suggested fix: add an integration test that runs `VipsImageCompressor` over a fixture image with GPS EXIF and asserts the output buffer parsed by `exifread` has zero `GPS*` keys. Independent of storage.
- Failing test: `tests/integration/imaging/test_exif_strip.py::test_gps_tags_removed`.

### #19 REQUEST_CHANGES — No CSRF/SSE auth story for `/coach/chat`
- Evidence: spec §9.4 SSE stream; no mention of how EventSource (which cannot set `Authorization` header in browsers) authenticates. Mobile is fine, web is broken.
- Why it matters: web client cannot consume the coach. Workaround (`?token=...` in URL) leaks JWT into server logs.
- Suggested fix: short-lived SSE ticket (`POST /coach/chat/ticket` returns 30s opaque token) consumed once on `EventSource` connect.
- Failing test: `tests/contract/test_sse_auth.py::test_eventsource_cannot_use_bearer_directly`.

### #20 REQUEST_CHANGES — pgvector HNSW index has no `m` / `ef_construction` and no recall test
- Evidence: spec §7 `CREATE INDEX ON foods USING hnsw (embedding vector_cosine_ops);` — defaults `m=16, ef_construction=64` are too low for 1536-dim and a large catalog.
- Why it matters: silent recall@10 collapse → bad food matches in vision pipeline → bad food_logs → bad kcal → bad recalibration. Cascade.
- Suggested fix: `WITH (m=32, ef_construction=200)`; commit a recall benchmark in `tests/perf/test_vector_recall.py` against a frozen query set; gate on recall@10 ≥ 0.95.
- Failing test: `tests/perf/test_vector_recall.py::test_recall_at_10_above_threshold`.

### #21 REQUEST_CHANGES — Architect agent files disagree on vector DB and embedding ownership
- Evidence:
  - `nova-backend-architect.md:26`: "Vector DB (Qdrant/Pinecone)"
  - `nova-nutrition-backend-architect.md:22`: "Vector DB (Qdrant preferred for self-host, Pinecone for managed)"
  - Spec §2: "pgvector" inside `timescale/timescaledb-ha:pg16`.
- Why it matters: agents will, on next prompt, propose Qdrant migrations contradicting the locked decision. Source-of-truth ambiguity.
- Suggested fix: edit both architect agent files to say "pgvector on Postgres (per spec §2). Qdrant/Pinecone explicitly rejected — single-DB cost/ops winner at MVP scale."
- Failing test: n/a (doc lint: `grep -r "Qdrant\|Pinecone" .claude/agents/` should return zero outside an explicit "rejected alternatives" block).

### #22 REQUEST_CHANGES — Nutrition generator agent emits `firebaseImageUrl` placeholder; spec defers image storage
- Evidence: all 2000 catalog records have identical `firebaseImageUrl: https://storage.googleapis.com/tu-proyecto/placeholder.webp`. Spec §2 / §18: image storage deferred. The catalog field is a Firebase URL but the spec leans Postgres-only with storage TBD.
- Why it matters: contract drift. If we ship as-is, every recipe card shows the same placeholder, every `recipes.imagen_url` is a lie. Better to be nullable.
- Suggested fix: ingest sets `recipes.imagen_url = NULL` when value equals the placeholder; UI handles null. Track in `docs/qa/known-data-gaps.md`.
- Failing test: `tests/data/test_catalog_ingest.py::test_placeholder_url_is_nulled`.

### #23 REQUEST_CHANGES — Plan §9.5 "Random shuffle" is non-deterministic and untestable
- Evidence: spec §9.5 step 3: "Random shuffle + embedding similarity score against profile."
- Why it matters: cannot write a stable test for plan generation; cannot reproduce a user-reported bad plan.
- Suggested fix: seeded RNG, seed stored on `plans.generation_seed`; regeneration must accept a seed and reproduce.
- Failing test: `tests/unit/application/plan/test_generation_deterministic.py::test_same_seed_yields_same_plan`.

### #24 REQUEST_CHANGES — Spec §9.5 "Avoid repeating same recipe >2× per week" undefined for week ≠ 7
- Evidence: spec allows `tipo enum('dia','semana','mes')`; rule "≤2/week" is unspecified for `mes`.
- Why it matters: edge case in domain logic; will fail or be inconsistent.
- Suggested fix: state rule as "≤ 2 occurrences per rolling 7-day window for plans of `tipo='semana'|'mes'`; n/a for `dia`."
- Failing test: `tests/unit/domain/plan/test_repetition_rule.py::test_monthly_plan_caps_per_week`.

### #25 INFO — Catalog duplicates by normalized name (4 collisions, low severity)
- Evidence: `'mujadara libanesa de lentejas y arroz'` ×3; `'bowl de atn con quinoa y edamame'`, `'sopa vietnamita pho de pollo'`, `'lomo saltado peruano magro'` ×2 each.
- Why it matters: minor; could be intentional variants. But QA suite §11 flags duplicates.
- Suggested fix: append distinguishing suffix or deduplicate. Low priority.

### #26 INFO — Catalog has 40 batch prefixes (`b01_..b40_`), all of size 50
- Evidence: ID prefix analysis. Suggests LLM batch generation; good for provenance tracking.
- Why it matters: add provenance column `source_batch` to `recipes` so we can quarantine a bad batch later.

---

## Missing Tests (to be written before merge of first feature PR)

Domain (Hypothesis):
- `MacroBreakdown` invariant property test (tolerance locked per finding #8).
- `Mifflin-St Jeor` symmetry: `bmr(hombre, ...) - bmr(mujer, ...) == 166 ± 5` over the full bounded input space.
- `KcalRange.max - min == 200` invariant.
- `Recipe` composition: `Σ component_macros == recipe_macros` within ε.
- `Plan` state machine: illegal transitions raise.
- `Recalibration.blend` bounded ±15% (finding #10).

Nutrition safety (deterministic, named):
- Allergen hard-exclude on every plan and every swap (parametrised over all 9 allergens).
- Pediatric (<18) and elderly (>75) bound caps.
- Diabetes type-2 sugar ceiling per recipe.
- Plateau symmetry (loss + gain trigger recalibration).
- Energy balance sanity: `Δpeso_predicho × 7700 ≈ Σ(kcal_in − tdee)` ±25% over 14d.

Catalog data quality (CI gate):
- Unknown allergen rejection (#1).
- Allergen-by-ingredient false-negative check (#2) per allergen.
- Allergen ∩ condition vocabulary disjoint (#3).
- Conditions in canonical enum (#4).
- Min records per meal_time (#5).
- Catalog enum values ⊆ DB enums (#6).
- Diabetes recipes have sugar field (#7).
- Placeholder URL nulled (#22).

Concurrency:
- `one_active_plan` 50 parallel POSTs → 1 active.
- `one_current_goals` 50 parallel recalibrations → 1 row (#9).
- Refresh-token family revoke (#15).
- Idempotency-Key replay (#11).

Integration / contract:
- Schemathesis full run against openapi.json.
- EventSource auth ticket flow (#19).

Security:
- EXIF strip on every CompressionProfile (#18).
- Argon2id parameter assertion.
- JWT expired/tampered/wrong-kid → 401.
- IDOR matrix: user A reads user B `/food_logs/{id}` → 404 (never 403).
- Rate limit per spec (60/5/10).

AI evaluation harness (must exist before any `gpt-4o` call ships):
- Vision golden set: ≥100 LatAm + US dishes with nutritionist ground truth; metrics: item P/R ≥ 0.75, kcal MAE ≤ 80, Brier ≤ 0.20.
- Coach LLM-as-judge rubric over 50 scenarios.
- STT WER ≤ 0.10 over 30 utterances.
- Embedding swap recall@5 Jaccard ≥ 0.7 (and pgvector recall@10 ≥ 0.95 — #20).

Performance baselines (committed):
- `GET /me/targets` p95 < 80 ms.
- `GET /plans/active` p95 < 150 ms.
- Non-photo `POST /logs/food` p95 < 200 ms.
- Vision job E2E p95 < 8 s with VCR'd OpenAI.

---

## Migration Safety

**N/A** — no migrations exist yet. Note for the first migration PR:
- `0001_init.py` must apply `CREATE EXTENSION` statements idempotently (`IF NOT EXISTS`).
- Hypertables created via `SELECT create_hypertable(..., if_not_exists => TRUE)`.
- `downgrade()` must `DROP TABLE` in reverse FK order and `DROP EXTENSION` last (or omit extension drop, with comment).
- Test `upgrade → downgrade → upgrade` in CI; the matrix runs against an empty DB and a 10k-row seeded DB.
- All partial unique indexes (`one_active_plan`, `one_current_goals` per #9) created with explicit names.

---

## Telemetry Requirements (must ship with first feature)

Metrics (Prometheus):
- `http_request_duration_seconds{route,method,status}` histogram with p50/p95/p99 buckets per route SLO.
- `openai_tokens_total{model,kind=in|out,user_id_bucket}` counter.
- `openai_cost_usd_total{model,feature}` counter.
- `vision_job_duration_seconds` histogram with VCR vs live label.
- `arq_queue_depth{queue}` gauge; `arq_job_retries_total{task,outcome}` counter.
- `catalog_ingest_rejected_total{reason}` counter (per data-quality gate).
- `allergen_exclusion_applied_total{allergen}` counter (proof the hard-exclude fires).
- `recalibration_triggered_total{motivo}` counter.
- `auth_refresh_family_revoked_total` counter (#15).

Logs (structlog JSON, mandatory fields):
- `request_id`, `user_id` (hashed), `trace_id`, `route`, `latency_ms`, `status`.
- Never: `email`, raw `condicion`, `alergia`, `peso_kg`, `coach_message_content`. CI grep gate per QA mandate.

Traces (OTel):
- Span per OpenAI call with `model`, `prompt_sha256`, `tokens_in/out`, `cost_usd`.
- Span per Arq task with `task_name`, `retry_count`.

Alarms (initial):
- `openai_cost_usd_total[1d]` > $X → page.
- p95 SLO miss for 10 min → page.
- `catalog_ingest_rejected_total` non-zero on deploy → block.
- `auth_refresh_family_revoked_total` non-zero → page (active attack signal).

---

## Sign-off Conditions

The spec moves from REQUEST_CHANGES → APPROVE when all of the following are checked:

- [ ] Findings #1, #2, #3, #4, #5, #6 resolved in spec + catalog (BLOCK class).
- [ ] ADR-001 (allergen/condition canonical enums) committed.
- [ ] ADR-002 (recalibration formula, #10) committed.
- [ ] ADR-003 (vision confidence threshold + calibration evidence, #12) committed.
- [ ] ADR-004 (per-user OpenAI cost cap, #14) committed.
- [ ] ADR-005 (GDPR/LGPD erasure, #16) committed.
- [ ] Spec §6 macro tolerance constant resolved to a single value (#8).
- [ ] Spec §7 adds partial unique index for `nutritional_goals` (#9), `parent_id/family_id` for `refresh_tokens` (#15), `ai_prompts` table + `feature_flags` (#13).
- [ ] Spec §8 adds `Idempotency-Key` header semantics to all POST mutations (#11).
- [ ] Spec §9.4 adds SSE ticket auth (#19).
- [ ] Spec §9.5 declares deterministic seed (#23) and clarifies week-cap rule (#24).
- [ ] Spec §7 pgvector index gets `(m=32, ef_construction=200)` + recall-test commitment (#20).
- [ ] Architect agent files reconciled: pgvector locked, Qdrant/Pinecone explicitly rejected (#21).
- [ ] Catalog pre-ingest pipeline implemented with: allergen lookup table, condition normalisation, placeholder-URL nulling, schema validation; all 8 catalog data-quality tests passing in CI.
- [ ] Either ≥300 `snack` records added to catalog or `snack` removed from spec enums (#5).
- [ ] `docs/qa/known-data-gaps.md` documents that micronutrient/fiber/sugar/sodium enrichment is required before any condition-filtered plan generation ships (#7).

When green: spec is ready for `0001_init.py`. Not before.
