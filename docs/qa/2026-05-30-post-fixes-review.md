# NOVA Nutrition — Post-Fixes Independent QA Review

- Date: 2026-05-30
- Reviewer: `nova-qa-elite` (second pass)
- Scope: verify the 4 fix commits against the 26 findings of `docs/qa/2026-05-30-pre-implementation-review.md` and surface new issues.
- Commits audited:
  - `5d46c04` docs(adr): foundational ADRs 0001-0005
  - `4db84d6` docs(spec): apply QA pre-implementation review fixes
  - `4db3e4f` chore(agents): reconcile architects to pgvector
  - `ef5f385` docs(spec): catalog ingest cleanup pipeline design

---

## Verdict

**REQUEST_CHANGES** — but materially closer to APPROVE than the first pass.

The senior closed the design-level findings well: schema patches, ADRs, ingest-pipeline spec, and SSE/idempotency/cost-cap contracts are all sound. The remaining gap is **execution discipline**: catalog data is still untouched on disk, the ingest pipeline is design-only (no `scripts/audit_catalog.py`), the clinical generator agent is stale (still emits ±5 kcal, no `sesame`, no `snack`), and several cross-doc inconsistencies survived the patch round (DELETE /me / cancel-deletion endpoint missing, allergens-denorm trigger DDL absent, plan state machine still informal, FK cascades from `users` not actually expressed in SQL).

The blockers that remain are not "argue the design" blockers — they are "the document still says X in one place and Y in another" or "the design says trigger does this, the DDL does not include the trigger".

Implementation of `0001_init.py` can begin **only** once: (1) recipes.allergens sync trigger DDL is in spec, (2) ON DELETE CASCADE chain from `users(id)` is in spec SQL (not just in ADR-0005 prose), (3) plan state machine is encoded somewhere (transition table or explicit guard contract), (4) generator agent is patched (sesame, snack, ±2% tolerance, spec §21 alignment), (5) `POST /me/cancel-deletion` is added to §8 or removed from ADR-0005.

---

## Risk Score

| Dimension | Pre-1st-review | Senior self-reported post-fix | Independent re-check |
|---|---:|---:|---:|
| clinical  | 4 | 1 | **2** (data still dirty; sesame/snack absent in generator) |
| security  | 3 | 1 | **2** (FK cascades from users not in SQL; SSE ticket cleanup job missing; OTP/cost-cap not enumerated in §11 errors) |
| perf      | 2 | 2 | **2** (HNSW tuned, recall test promised — still no committed baselines; coach_sse_tickets unbounded growth) |
| data      | 5 | 2 | **4** (spec/ADRs sound, catalog file unchanged: still 0 snacks, still `mustard`, still 100% placeholder URLs, still 64 condition labels including `egg`/`shellfish` leaks; gates are designed but unbuilt) |
| rollback  | 3 | 2 | **2** (ADRs lock decisions; expand-contract migration example still absent; recipes.allergens trigger DDL absent) |

Net: senior's self-report is over-optimistic by ~1 point on every axis. Real progress was made; the gap is execution and last-mile consistency.

---

## Per-finding verification table

| # | Sev (1st pass) | Senior claim | Independent verification | Evidence |
|---|---|---|---|---|
| #1 | BLOCK — unknown allergens (`mustard`) in catalog | "Closed by §20 gate 3 + ADR-0001" | **PARTIAL** — schema/ADR/spec gate define closed enum incl. `sesame`; **data file still contains `mustard`** (1 rec) and the auditor script does not exist. Will block ingest, not unsafe at runtime, but the finding is not "closed", it is "blocked-on-ingest". | `docs/adr/0001-…:30`; spec L161-163; catalog audit: `unknown allergens: ['mustard']` |
| #2 | BLOCK — 161 dairy / 169 gluten / 144 purine false negatives | "Closed by ingest gate 5 (ingredient lexicon)" | **PARTIAL** — gate 5 designed (`docs/superpowers/specs/2026-05-30-catalog-ingest-pipeline.md:61-81`) with ≥50 keyword mappings. Lexicon is **English-keyword-only** ("salmon", "atun") despite ingredients being in Spanish (e.g. "leche de almendras sin azúcar"). Gate 5 §62 mentions "unaccent, lowercase, NFKC" normalisation — good — but the lexicon as written does not list "salmón", "atún", or "yogur" with accents removed in the table itself. Reviewer must verify the lexicon implementation strips accents from BOTH sides at runtime. Script unbuilt. | catalog spec L65-81; catalog row b01_001 has "almendras laminadas" → `tree_nuts` correctly tagged in this case, but b01_001 also has "leche de almendras sin azúcar" — explicitly NOT dairy (almond milk), so this specific row is actually fine. The 161 false negatives finding from pass 1 was heuristic; gate 5 will catch real cases. |
| #3 | BLOCK — allergens leaking into conditions | "Closed by gate 4 disjointness check" | **APPLIED (design)** — catalog spec L57-58 enforces `(recommended ∪ contraindicated) ∩ allergen_enum == ∅`. ADR-0001 §3 codifies. Data still has 26 leaking rows (audit: `egg`, `shellfish` in conditions); gate will reject them on ingest. | catalog spec L57; ADR-0001 L36-37; live data still leaking. |
| #4 | BLOCK — 62 distinct condition labels | "Closed by ADR-0001 + canonical_conditions enum" | **PARTIAL** — ADR-0001 §2 declares "Python StrEnum ≤25 values" and `condition_vocabulary` table, but the **canonical list is not enumerated anywhere**. Catalog ingest spec §4 mentions only 3 example collapses. Implementation cannot proceed without the actual 25 values. | ADR-0001 L32-34; catalog spec L125-128 ("a separate normalisation table" — undefined). |
| #5 | BLOCK — 0 snack records | "Closed by spec §22; chose option (a) generate ≥100 snacks" | **NOT_FIXED** — spec §22 declares "(a) is the chosen path" but **no snack records have been generated**. The generator agent (`nova-clinical-nutrition-generator.md:74`) still lists only `"[breakfast / lunch / dinner]"` as mealTime — it cannot generate snacks. The blocker is acknowledged but the work is owed, and the generator is incapable of producing snacks until edited. | spec L744-762; generator agent L74; live catalog: `mealtime: {lunch:800, breakfast:600, dinner:600}`. |
| #6 | BLOCK — identifier-language schism | "Closed by spec §21" | **PARTIAL** — §21 declares Spanish for DB enums, English for catalog input, mapping bridge in §20/§21 + catalog spec §4. Sound design. **Generator agent NOT updated**: line 85 still says "todos los keys JSON están en inglés snake_case" without qualifying that this is *input format*, not *DB format*. Spec §21 itself admits "the generator agent is to be updated separately" — that update did not happen in this commit set. | spec L716-739; generator agent L85; spec §21 admits the gap L720-722. |
| #7 | REQUEST_CHANGES — missing `fiber/sugar/sodium/sat_fat` in catalog | (not in commit messages) | **NOT_FIXED in catalog**; **PARTIAL in spec** — `foods` table has these fields (spec L135-137) but `recipes` table only has `fibra int` (L143), no `azucar/sodio_mg/grasa_sat`. Diabetes contraindication filter cannot run at recipe level. Catalog data file lacks these fields entirely. | spec L142-143 (recipes lacks azucar/sodio_mg/grasa_sat); catalog records carry only `proteinG/carbsG/fatG`. |
| #8 | REQUEST_CHANGES — ±5% vs ±10% vs ±5 kcal | "Locked at ±2%" | **APPLIED in spec/ADRs**, **NOT_FIXED in generator agent**. Spec §6 + catalog spec gate 2 both reference `MACRO_TOLERANCE = 0.02`. QA mandate L124 still says `±10%` (`p·4 + c·4 + g·9 ≈ kcal ±10%`). Generator agent L84 still says `±5 kcal absolute`. Two of three stale. | spec L67; catalog spec L46-48; QA mandate L124; generator L84. |
| #9 | REQUEST_CHANGES — `one_current_goals` unindexed | "Added partial unique index" | **APPLIED** — spec L127-128 has the exact index. | spec L127. |
| #10 | REQUEST_CHANGES — recalibration formula underspecified | "Locked in ADR-0002 + spec §9.2" | **APPLIED** — ADR-0002 + spec §9.2 are formally precise (OLS, 0.5/0.5 blend, ±15% clamp, 14-day cool-down). One small inconsistency: ADR-0002 L72 adds winsorisation of >3σ daily deltas; spec §9.2 does not mention winsorisation. Pick one and align. | ADR-0002 L29-45, L72; spec L394-429. Also: `nova-backend-architect.md:22` still says "rolling averages, adaptive thermogenesis coefficients" — stale (does not mention OLS / blend / clamp / cool-down). |
| #11 | REQUEST_CHANGES — no idempotency key on vision pipeline | "Added §8 Idempotency-Key contract + food_logs.idempotency_key column" | **APPLIED** — spec L365-376 details the contract; L196-203 has the column + partial unique index. | spec L196-203, L365-376. |
| #12 | REQUEST_CHANGES — `>0.7` magic number | "Locked in ADR-0003" | **APPLIED** — ADR-0003 codifies threshold = 0.70, quarterly calibration review, reliability diagram committed under `docs/qa/vision-calibration/`. | ADR-0003 entire. |
| #13 | REQUEST_CHANGES — no prompt versioning / kill switch | "Added ai_prompts + feature_flags tables" | **APPLIED** — spec L258-272. `one_active_prompt_per_name` partial unique index present. `food_logs.prompt_sha256` (L198-199) wires provenance. `coach_messages` does NOT carry `prompt_sha256` (only `food_logs` does); ADR-0003 L34 claims `coach_messages.prompt_sha256` exists — **spec/ADR drift**. | spec L242-244 (coach_messages, no prompt_sha256); ADR-0003 L34. |
| #14 | REQUEST_CHANGES — no per-user OpenAI cost cap | "Locked in ADR-0004" | **APPLIED** — ADR-0004 + spec §12.OpenAI-cost-cap match: $1.50/user/day, 429 response, kill-switch flag, alarm at 80%. One drift: original finding suggested 402; ADR settled on 429 — acceptable. | ADR-0004; spec L543-553. |
| #15 | REQUEST_CHANGES — refresh-token family-revoke missing | "Added family_id/parent_id/reused_at" | **APPLIED** — spec L86-94 with reuse semantics described. No SQL trigger; reuse-detection is application code. Index on `family_id` present. | spec L86-94. |
| #16 | REQUEST_CHANGES — no GDPR/LGPD erasure | "Locked in ADR-0005" | **PARTIAL** — ADR-0005 design is comprehensive (soft-delete + 30d grace + cancel + hard delete). **Spec §8 missing `POST /me/cancel-deletion` endpoint** referenced by ADR-0005 L23. **Spec §7 FK declarations are informal** (`user_id uuid fk`) and do NOT express `ON DELETE CASCADE` from `users(id)` — ADR-0005 L39 claims they will. **`progress_photos` listed in ADR-0005 L34 but that table does not exist in spec §7.** | spec L298-302 (no cancel endpoint); spec L172/190/215 (informal `fk`); ADR-0005 L23, L34, L39. |
| #17 | REQUEST_CHANGES — plan state machine no illegal-transition guards | "Closed by spec" | **NOT_FIXED** — commit message claims #17 closed. Spec §9.3 (L431-441) still only describes the *forward* happy path; no transition table, no DB CHECK / trigger, no `plans.version` column for optimistic locking. Property test cannot exist without the formal state machine. | spec L431-441; schema L172-179 has no `version` column. |
| #18 | REQUEST_CHANGES — no EXIF strip verification harness | "Added §10 verification harness" | **APPLIED** — spec L509-521 specifies `_assert_exif_stripped` helper, `EXIFLeakError`, and the integration test path. Test fixture not yet written but contract is precise. | spec L509-521. |
| #19 | REQUEST_CHANGES — no CSRF/SSE auth story | "Added `POST /coach/sse-ticket` + table" | **APPLIED with a defect** — spec L278-284 has `coach_sse_tickets` (token_hash + expires_at + ON DELETE CASCADE from users). §12 SSE-ticket flow L555-564 details one-shot semantics. **Index `ON coach_sse_tickets(expires_at)` exists but no cleanup job is specified** — expired rows accumulate. See new issue #29. | spec L278-284, L555-564. |
| #20 | REQUEST_CHANGES — HNSW untuned | "Added `(m=32, ef_construction=200)` + recall test commitment" | **APPLIED** — both `foods` (L138-139) and `recipes` (L166-167) indexes tuned; recall@10 ≥ 0.95 test path committed. | spec L138-139, L165-167. |
| #21 | REQUEST_CHANGES — architect agents say Qdrant | "Reconciled both to pgvector" | **PARTIAL** — both agent **bodies** updated (`nova-backend-architect.md:26`, `nova-nutrition-backend-architect.md:22`). **YAML frontmatter `description` field NOT updated**: `nova-nutrition-backend-architect.md:3` still says "polyglot persistence (Postgres, TimescaleDB, Qdrant/Pinecone, Redis)" — visible whenever the agent is listed to the dispatcher. `nova-backend-architect.md:3` description still says "storage layers (PostgreSQL, TimescaleDB, Vector DBs, Redis)" (vaguer, less wrong, but still leaves the door open). | grep output above. |
| #22 | REQUEST_CHANGES — `firebaseImageUrl` placeholder | "Closed by catalog ingest gate 8 — placeholder → NULL" | **APPLIED in design** — gate 8 specified (catalog spec L96-101). Catalog file itself still 100% placeholder. | catalog spec L96-101; live audit: 2000/2000 placeholder. |
| #23 | REQUEST_CHANGES — non-deterministic plan shuffle | "Added plan_generation_seeds + §9.5" | **APPLIED** — table at spec L274-276, contract at L451-455. `(profile_snapshot, catalog_version, seed)` triple specified. | spec L274-276, L451-455. |
| #24 | REQUEST_CHANGES — week-cap undefined for `mes` | "Added rule" | **APPLIED** — spec L461-465 declares `≤2/7d rolling` and additionally `≤4/30d` for `tipo='mes'`. Deterministic and testable. | spec L461-465. |
| #25 | INFO — duplicates by normalized name | "Out of scope of this commit set" | **NOT_FIXED** — catalog file unchanged; ingest gate 6 will flag them (warn for d>0, fail only for d==0 same mealtime). Acceptable for INFO severity. | catalog spec L84-89; live data unchanged. |
| #26 | INFO — batch provenance | "Added `recipes.source_batch text null`" | **APPLIED** — spec L146-147. | spec L146-147. |

Summary: **APPLIED 14, PARTIAL 8, NOT_FIXED 3, REGRESSED 0, INFO unchanged 1.**

The 3 NOT_FIXED are #5 (snack data still missing & generator can't make snacks), #17 (plan state machine still informal — commit msg claimed closed; not), #25 (acceptable, INFO).

---

## New issues discovered (#27+)

### #27 BLOCK — `recipes.allergens` denormalised array has no sync mechanism
- Evidence: spec L148-150 declares `recipes.allergens text[]` denormalised "Source of truth remains recipe_allergens; trigger keeps this column in sync." **No trigger DDL anywhere in spec §7.** Plan generation (L457) relies on `recipes.allergens && $alergias` for allergen hard-exclude — if the trigger is omitted or buggy, **silent allergy violations** at recipe level. This is the spec's safety pillar; it cannot rest on "the implementer will add a trigger".
- Suggested fix: add the trigger DDL inline in spec §7, e.g.:
  ```sql
  CREATE OR REPLACE FUNCTION sync_recipe_allergens() RETURNS trigger AS $$
  BEGIN
    UPDATE recipes SET allergens = COALESCE((
      SELECT array_agg(allergen::text ORDER BY allergen) FROM recipe_allergens WHERE recipe_id = COALESCE(NEW.recipe_id, OLD.recipe_id)
    ), '{}') WHERE id = COALESCE(NEW.recipe_id, OLD.recipe_id);
    RETURN NULL;
  END $$ LANGUAGE plpgsql;
  CREATE TRIGGER trg_sync_recipe_allergens
    AFTER INSERT OR UPDATE OR DELETE ON recipe_allergens
    FOR EACH ROW EXECUTE FUNCTION sync_recipe_allergens();
  ```
- Failing test: `tests/integration/recipes/test_allergens_sync.py::test_inserting_recipe_allergen_updates_denorm_array` + a generated-property test asserting `recipes.allergens` always equals `array_agg(recipe_allergens.allergen)` per recipe.

### #28 BLOCK — `users(id)` ON DELETE CASCADE chain is asserted by ADR-0005 but absent from spec §7 SQL
- Evidence: ADR-0005 L39 says "FK constraints use ON DELETE CASCADE from `users(id)` for everything except `audit_log`". Spec §7 schema uses informal `user_id uuid fk` on `refresh_tokens`, `nutritional_goals`, `plans`, `food_logs`, `fasting_sessions`, `coach_conversations`, etc. — none of these are real `REFERENCES users(id) ON DELETE CASCADE`. Implementer will guess; GDPR/LGPD erasure may leave orphan rows.
- Suggested fix: rewrite every `user_id uuid fk` as `user_id uuid not null references users(id) on delete cascade` in spec §7. Add a Postgres test that deletes a user and asserts `count(*) = 0` for every owned table.
- Failing test: `tests/integration/identity/test_user_erasure.py::test_all_owned_tables_cascade_on_user_delete`.

### #29 REQUEST_CHANGES — `coach_sse_tickets` has no cleanup job — unbounded growth
- Evidence: spec L278-284 creates the table with an index on `expires_at` but no scheduled deletion. ADR-0005 lists it in the per-user hard-delete cascade, but org-wide expired-row cleanup is unspecified. At 60 req/min/user × N users × 30-day retention, the table grows linearly.
- Suggested fix: add an Arq cron task `cleanup_expired_sse_tickets` that runs every 5 minutes: `DELETE FROM coach_sse_tickets WHERE expires_at < now() - interval '1 minute'`. Document in spec §13 (observability) with metric `sse_tickets_expired_total`.
- Failing test: `tests/integration/coach/test_sse_ticket_cleanup.py::test_expired_tickets_are_pruned`.

### #30 REQUEST_CHANGES — `coach_messages` missing `prompt_sha256` (ADR/spec drift)
- Evidence: ADR-0003 L34 claims "Every OpenAI call records `prompt_sha256` on the resulting row (`food_logs.prompt_sha256`, `coach_messages.prompt_sha256`)". Spec L242-244 `coach_messages(id, conv_id, role, content, tokens_in, tokens_out, created_at)` — no `prompt_sha256` column.
- Suggested fix: add `prompt_sha256 text null` to `coach_messages`.
- Failing test: `tests/integration/coach/test_prompt_version_recorded.py::test_coach_message_carries_prompt_sha`.

### #31 REQUEST_CHANGES — `POST /me/cancel-deletion` referenced by ADR-0005 but missing from spec §8
- Evidence: ADR-0005 L23 "During grace, the user can `POST /me/cancel-deletion` to abort." Spec §8 (L298-305) lists only `DELETE /me` and `GET /me/export`.
- Suggested fix: add `POST /me/cancel-deletion` to spec §8, with semantics: clears `users.deletion_requested_at`, re-enables sessions (or requires re-auth).
- Failing test: `tests/integration/identity/test_user_erasure.py::test_cancel_deletion_aborts_grace_window`.

### #32 REQUEST_CHANGES — `progress_photos` table named by ADR-0005 but not declared in spec §7
- Evidence: ADR-0005 L34 lists `progress_photos` in hard-delete cascade; spec §7 has no such table. API §8 has `POST /progress/photo` (L345). Schema gap.
- Suggested fix: add `progress_photos(id uuid pk, user_id uuid fk on delete cascade, taken_at timestamptz, image_url text, ...)` to spec §7.

### #33 REQUEST_CHANGES — `nova-clinical-nutrition-generator` agent is stale on 4 dimensions
- Evidence:
  - Line 71 allergen enum: `["dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg", "soy"]` — **missing `sesame`** (ADR-0001 §1 requires it).
  - Line 74 mealTime: `"[breakfast / lunch / dinner]"` — **missing `snack`** (root cause of #5; this agent literally cannot generate snacks today, so spec §22 option (a) is impossible until this is patched).
  - Line 84 macro tolerance: `±5 kcal` absolute — contradicts spec §6 (`±2%`, single source of truth).
  - Line 85 "todos los keys JSON están en inglés snake_case" — true for catalog input, but the agent emits no warning that DB persistence is Spanish (per spec §21). Not a bug, but a hand-off ambiguity that nearly bit pass 1.
- Suggested fix: surgical edit to the agent file aligning all four points; bump version note in the agent description.

### #34 REQUEST_CHANGES — Architect agents' frontmatter `description` still names "Vector DBs" / "Qdrant/Pinecone"
- Evidence:
  - `nova-nutrition-backend-architect.md:3` (YAML frontmatter description string): `"polyglot persistence (Postgres, TimescaleDB, Qdrant/Pinecone, Redis)"` — unchanged.
  - `nova-backend-architect.md:3`: `"storage layers (PostgreSQL, TimescaleDB, Vector DBs, Redis)"` — same vibe.
- Why it matters: the description is what the dispatcher and downstream agents see when deciding when to invoke. Re-introducing Qdrant via prompt influence is the exact risk pass 1 #21 raised. Body was fixed; the visible surface was not.
- Suggested fix: rewrite both descriptions to say "polyglot persistence (Postgres + TimescaleDB + pgvector + Redis)".

### #35 REQUEST_CHANGES — `nova-backend-architect.md:22` recalibration prose contradicts ADR-0002
- Evidence: line 22 says "When observed weight loss/gain deviates from predictions (Mifflin-St Jeor baseline), trigger metabolic re-estimation using **rolling averages, adaptive thermogenesis coefficients**, and TDEE recalculation." ADR-0002 locks **OLS slope**, **0.5/0.5 Mifflin/EB blend**, **±15% clamp**, **14d cool-down** — no rolling-average smoothing, no "adaptive thermogenesis coefficient". Stale guidance will leak into future PR designs.
- Suggested fix: rewrite line 22 to reference ADR-0002 and use its terminology verbatim.

### #36 REQUEST_CHANGES — `canonical_conditions` enum values never enumerated
- Evidence: ADR-0001 §2 says `"Python StrEnum in app/recipes/domain/conditions.py (≤25 values)"`; catalog spec §4 says "a separate normalisation table collapses duplicates". The actual 25 values, the ICD-10 mapping, and the legacy-collapse table do not exist anywhere in the spec/ADR set. Implementation cannot start without them; pass 1 #4 is therefore only design-resolved, not data-resolved.
- Suggested fix: append an Appendix to ADR-0001 listing the 25 canonical conditions with ICD-10 categories, plus the legacy→canonical mapping.

### #37 REQUEST_CHANGES — Spec §11 (Errors) does not enumerate the new error classes introduced by these fixes
- Evidence: §11 lists `DomainError → ValidationError, NotFoundError, ConflictError, BusinessRuleViolation`. New paths introduced by this commit set: 423 (OTP locked, spec L101), 429 cost-cap (spec L550), 401 SSE ticket invalid (spec L562). None mapped to a domain error class.
- Suggested fix: add `LockedError → 423`, `RateLimited → 429`, `CostCapExceeded → 429`, `AuthTicketInvalid → 401` to the hierarchy.

### #38 INFO — Spec §14 (Testing) is unchanged despite ADRs naming specific test files
- Evidence: spec L580-590 still says "tests/unit/domain", "tests/integration", etc. — no reference to `tests/data/test_catalog_*`, `tests/ai/test_vision_calibration`, `tests/integration/identity/test_user_erasure`, `tests/integration/feature_flags/test_kill_switch_*`. Five ADRs reference test files that the testing section does not classify.
- Suggested fix: add subsections `tests/data/` (catalog audits), `tests/ai/` (AI evals), `tests/perf/` (HNSW recall, k6 baselines), and list the specific files committed by the ADRs.

### #39 INFO — ADR-0002 winsorisation rule is in the ADR but not in spec §9.2
- Evidence: ADR-0002 L72 "a single >3σ daily delta is winsorised to the 95th percentile of the window before OLS". Spec §9.2 (L394-429) describes the OLS chain without this preprocessing step. The OLS-on-winsorised-data is a different formula from OLS-on-raw-data.
- Suggested fix: add a single line in §9.2 explicitly noting the winsorisation step (or remove from ADR if not adopted).

---

## Missing tests (still owed despite design fixes)

All of these are new design surface that has no committed test:

- `tests/integration/recipes/test_allergens_sync.py::test_inserting_recipe_allergen_updates_denorm_array` (#27)
- `tests/integration/identity/test_user_erasure.py::test_all_owned_tables_cascade_on_user_delete` (#28)
- `tests/integration/identity/test_user_erasure.py::test_cancel_deletion_aborts_grace_window` (#31)
- `tests/integration/coach/test_sse_ticket_cleanup.py::test_expired_tickets_are_pruned` (#29)
- `tests/integration/coach/test_prompt_version_recorded.py::test_coach_message_carries_prompt_sha` (#30 — currently impossible, column missing)
- `tests/integration/identity/test_otp_lockout.py::test_5_failed_attempts_lock_15min` (new OTP lockout invariant L96-102)
- `tests/integration/identity/test_refresh_rotation.py::test_reused_token_revokes_family` (#15 — spec patched, test still owed)
- `tests/integration/tracking/test_idempotency.py::test_replay_returns_same_response_with_header` (#11 — spec patched, test still owed)
- `tests/perf/test_vector_recall.py::test_recall_at_10_above_threshold` (#20 — index tuned, benchmark not committed)
- `tests/integration/coach/test_sse_ticket_one_shot.py::test_ticket_consumed_on_first_use` (#19 — one-shot semantic)
- `tests/integration/imaging/test_exif_strip.py::test_gps_tags_removed_per_profile` (#18 — fixture and harness owed)
- `tests/unit/domain/plan/test_state_machine.py::test_illegal_transitions_raise` (#17 — still no state machine to test)
- `tests/data/test_catalog_*` (all 8 gates from §20 — none built; the entire `scripts/audit_catalog.py` script is design-only)

Plus the original pass-1 missing test list (allergen hard-exclude property, Mifflin symmetry, KcalRange invariant, recipe composition, recalibration property, clinical safety scenarios, AI eval harness, schemathesis, IDOR matrix, performance baselines) — none of those have been committed.

---

## Telemetry gaps still present

Pass 1 specified a Prometheus metric set; none committed. New gaps introduced by this commit set:

- `cost_cap_blocked_total{cap=user|org}` counter (ADR-0004 implies but does not require).
- `sse_tickets_issued_total`, `sse_tickets_consumed_total`, `sse_tickets_expired_total` (#29).
- `recalibration_skipped_total{reason}` — ADR-0002 L70 mentions; spec §13 does not list it.
- `idempotency_replay_total{endpoint}` — needed to prove the contract works.
- `catalog_audit_gate_failed_total{gate}` — pass 1 had `catalog.ingest.unknown_allergen`; the new 8-gate design needs a labelled counter.

Spec §13 (L572-578) still only lists "request latency, OpenAI token usage, Arq queue depth". Significant under-specification.

---

## Sign-off conditions remaining

To move from REQUEST_CHANGES → APPROVE, the following must be true:

- [ ] **#27 fix**: `recipes.allergens` sync trigger DDL written in spec §7.
- [ ] **#28 fix**: every `user_id uuid fk` in spec §7 rewritten as `references users(id) on delete cascade`; `audit_log` uses `on delete set null`.
- [ ] **#17 fix**: plan state machine encoded — transition table in spec §9.3 + `plans.version int not null default 0` column + optimistic-locking contract.
- [ ] **#5 fix**: generator agent patched to allow `snack` mealtime AND ≥100 snack records generated (or option (b) chosen and `snack` removed from `meal_time` enum).
- [ ] **#30 fix**: `coach_messages.prompt_sha256 text null` added.
- [ ] **#31 fix**: `POST /me/cancel-deletion` added to spec §8.
- [ ] **#32 fix**: `progress_photos` table declared in spec §7.
- [ ] **#33 fix**: generator agent updated for sesame, snack, ±2% tolerance, §21 alignment.
- [ ] **#34 fix**: both architect agent YAML descriptions rewritten to remove Qdrant/Pinecone/"Vector DBs".
- [ ] **#35 fix**: `nova-backend-architect.md:22` rewritten to use ADR-0002 vocabulary.
- [ ] **#36 fix**: the 25 canonical conditions enumerated as an ADR-0001 appendix with ICD-10 mapping + legacy mapping table.
- [ ] **#37 fix**: spec §11 lists the new error classes (423/429/401 mappings).
- [ ] **#29 fix**: `coach_sse_tickets` cleanup job specified.
- [ ] **#39 fix**: spec §9.2 / ADR-0002 winsorisation reconciliation.
- [ ] QA mandate `±10%` reference (line 124 of `nova-qa-elite.md`) updated to `±2%` to match spec §6.
- [ ] Data-quality work: either the auditor script + cleaned catalog landed, OR an explicit ADR accepts "catalog ingest is gated to staging until pipeline ships; 0001_init.py creates schema only, no seed".

When all 16 items are checked: implementation may begin. Until then, the spec patches are good-faith design work that still contradicts itself in a handful of important places, and the data layer remains untouched.

---

## Closing note

The senior did real work — five ADRs and a substantive spec patch in one sitting is not nothing. The pattern of remaining defects is consistent: design-level decisions land in the spec/ADRs, but the **last-mile artifacts** (trigger DDL, FK cascade clauses, generator agent edits, missing endpoints, missing tables that ADRs reference) get skipped. A second sweep of "for every claim in an ADR, find it expressed in the spec SQL/API" would close most of #27–#37 in under an hour.

The catalog data file remains the single largest unaddressed risk — the spec now has the safety net (the 8 gates), but the net does not exist as code and the data still needs cleaning. The senior chose to "design first, build later"; that is defensible if and only if `0001_init.py` does not also seed the catalog. Make that explicit before the first migration ships.
