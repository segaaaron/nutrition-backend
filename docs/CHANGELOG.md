# Changelog

All notable changes to the NOVA backend. Commits are grouped by sprint, most recent first. Hashes match `git log --oneline`.

## [Sprint 9 — 0.4.0-beta.1] 2026-06-03 — Robustness sprint + vision cascade + ADRs 0022-0025

Owner will assign commit hashes at squash time. Entries follow Keep-a-Changelog sections within the existing sprint-grouped format.

### Added
- D1-D18 recalibration robustness pipeline: winsorise P5/P95, MAD outlier rejection (k=3), intake bias correction (Lichtman 1992 / Hill 2001), adaptive thermogenesis model (Müller 2015), intake physiological floor (≥0.5·BMR), UTC day-index contract.
- R1-R10 catalog hardening: `(col IS NOT NULL AND col ≤ X)` for critical condition columns, catalog completeness boot-guard (`scripts/catalog_completeness_audit.py`, fails boot >10 % NULL, warns >5 %).
- Vision cascade pipeline (gpt-4o-mini primary → gpt-4o fallback) behind `VISION_CASCADE_ENABLED` flag, default OFF until ADR-0025 gates met.
- Vision food prefilter (gpt-4o-mini low-detail) rejecting supplements / water / non-food / <20 kcal items before main pipeline. Default ON.
- SHA256 cross-user vision cache with PII strip + per-user matcher rerun.
- Vision rate limit 30 photos/hour/user, Redis sliding window, fail-closed 503 on Redis outage.
- Vision SETNX inflight lock preventing duplicate billing on concurrent submits.
- Redis pool explicit 50 connections.
- Cost cap pipeline collapsed 3 RTT → 1 RTT.
- Docker entrypoint auto-runs `alembic upgrade head` on every boot (`docker/entrypoint.sh`).
- Makefile + `scripts/db_change.py` guided dev workflow.
- Migration 0011 partial index on `vision_jobs(image_sha256)` for cache lookup performance.
- Mutmut closures: surviving mutants in recalibration, plan ranking, macro tolerance addressed.
- Prompt sanitiser with input delimiters in coach + nutrition agent prompts.
- Advisory PostgreSQL lock around recalibration concurrency path.
- Idempotency-Key honoured on `/plan/create` and `/logs/food/text` endpoints.
- ADR-0022 (recalibration robustness), ADR-0023 (catalog fail-closed), ADR-0024 (adaptive thermogenesis), ADR-0025 (vision cascade calibration gate).
- Tests: `tests/unit/core/test_cost_cap_pipeline.py`, `tests/unit/core/test_redis_pool.py`, `tests/unit/nutrition/test_macro_invariants.py`, `tests/unit/plan/test_allergen_invariant.py`, `tests/unit/plan/test_multi_condition.py`, `tests/integration/vision/*`.

### Changed
- Catalog Layer 1 SQL flips from include-on-NULL to exclude-on-NULL for critical condition columns (ADR-0023).
- BMR canonical source consolidated to `app/nutrition/domain/mifflin_st_jeor.py`; `app/plan/domain/macro_calculator.py` now delegates instead of re-implementing.
- Agent prompt files clarified to remove vaporware algorithm claims (Pareto / Kalman / PELT / NSGA-II / bioavailability) that had no backing implementation.
- Voice ingestion path (`/logs/food/text`): backend now accepts transcript only; device handles STT.
- `app/vision/infrastructure/openai_vision.py` returns `[]` on `json.JSONDecodeError` so cascade escalates instead of hard-failing.

### Deprecated
- `WHITELISTED_ROUTES` decorative constant (no enforcement) — slated for removal next sprint.
- Voice STT on backend (removed this sprint; flagging for users of older client builds).

### Removed
- `app/voice/infrastructure/whisper_client.py` and all Whisper wiring; backend no longer transcribes audio.
- Duplicate Mifflin-St Jeor implementation in plan domain (now delegates).
- Vaporware Idempotency-Key handling on `/coach/chat` and `/fasting/start` (those endpoints are not idempotent by nature; the header was accepted but ignored — removed to avoid misleading clients).

### Fixed
- D7: adaptive thermogenesis now uses bias-corrected intake mean instead of raw mean (double-count bug closed). Test: `test_at_uses_corrected_mean`.
- `datetime.utcnow()` → `datetime.now(timezone.utc)` across nutrition, vision, voice, plan, profile (deprecation warning + naive datetime risk).
- `float` → `Decimal` in voice transcript macro parser and `food_log` aggregation paths (precision parity with nutrition math, per ADR-0009).
- Recalibration race test deadlock (`tests/integration/nutrition/test_recalibration_concurrency.py`) using advisory lock.
- Layer 1 CKD condition gate f-string interpolation replaced with bind parameter (`app/plan/domain/condition_gates/ckd.py`).

### Security
- Full SQL injection audit on plan + catalog query paths: 0 injection vectors found, audit log committed.
- Prompt injection mitigations: input delimiters around user-provided fields in coach + nutrition prompts.
- Audit log immutability test (append-only verified at repository level).
- CI grep gate against PII tokens in log statements.
- HTTP 429 responses now include RFC 7231 / RFC 6585 compliant `Retry-After` header.

## [Sprint 8] 2026-05-31 — Ops + final docs + pre-launch QA

- `b20f10e` docs(qa): pre-launch review — known blockers + go/no-go checklist
- `b3341c5` docs(spec,readme,context): final §7-§22 patches + README + CONTEXT.md
- `1b09957` docs(ops): backup-recovery + deploy-dokploy runbooks + scripts

## [Sprint 7] 2026-05-31 — Billing + i18n + load + final migrations

- `ff0b8b8` feat(migration): 0004 food_log_aggregates + 0005 achievements_seed + 0006 billing
- `d997c63` test(load): k6 baseline scenarios (steady/spike/soak)
- `6bae63d` feat(scripts): seed_i18n.py — 5-locale translations for all canonical IDs
- `04710b1` feat(billing): Stripe + Mercado Pago + gateway router by country

## [Sprint 6] 2026-05-31 — Tracking expansion + grocery + gamification full

- `930ff89` feat(tracking): progress photos + EXIF strip + body composition
- `52ed804` feat(gamification): achievements catalog + streaks + levels + leaderboard
- `548ca46` feat(grocery): full bounded context — generate/scale/share/categorize
- `b71e958` feat(tracking): fasting sessions complete — start/stop/active/history/streak
- `2d4639e` feat(tracking): full food_log query API + totals + trends + micros

## [Sprint 5] 2026-05-31 — Notifications + gamification handlers + worker

- `c314cda` docs(spec,adr,qa): vision/coach §24 patch + ADR-0006 + golden eval design
- `f119189` test(coach,nutrition,unit): medical_refuse 20 + parser + intent + vision parse
- `42ff932` feat(scripts,worker): resolve_ingredients backfill + worker tasks + goals/today
- `9d318c5` feat(gamification): event handlers — meal/water/day → streaks + daily_goals
- `f4f28ea` feat(migration): 0003 push_tokens schema
- `52d6bd2` feat(notifications): web push (VAPID) + FCM scaffold + send dispatcher

## [Sprint 4] 2026-05-31 — Vision + voice + coach

- `b1ede9a` feat(coach): features A/B/C/D/E/F/G — proactive coach behaviours
- `3d9edb4` feat(coach): bounded context — 4-camino router + intent classifier + SSE
- `fb9b14a` feat(vision): STT whisper + text quick log + NLP food parser
- `dcb28ac` feat(vision): bounded context — photo upload + gpt-4o vision pipeline

## [Sprint 3] 2026-05-31 — Tracking baseline + observability

- `cb28ac9` docs(spec): §9.5 link Layer 1-4 implementations
- `cc7f869` test(plan,nutrition): allergen hard-exclude + recalibration + macro balance + state machine
- `2edf97e` feat(observability): healthz/readyz + Prometheus metrics + counters
- `ed33d18` fix(nutrition): subscribe handler to tracking-owned WeightLogged
- `2391db4` feat(tracking): water + weight logs + trend (Timescale)

## [Sprint 2] 2026-05-31 — Identity + profile + nutrition + recipes + plan L1-L4

- `4136cd3` feat(plan): create_plan orchestrator + arq task + endpoints
- `cdfec50` feat(plan): L4 LLM coherence pass mini + Redis 24h cache
- `c7e2204` feat(plan): L3 hybrid ranking (taste-EMA + cultural + prep + novelty + adherence)
- `a3ccb70` feat(plan): L2 macro-balanced shortlist with repetition cap
- `d673acc` feat(plan): state machine + L1 eligibility filter SQL deterministic
- `b15a636` feat(recipes): full bounded context — hybrid search trigram+pgvector + i18n
- `fedda3d` feat(nutrition): full bounded context — Mifflin + TDEE + macros + recalibration (ADR-0002)
- `91b0a44` feat(profile): full bounded context — user_profile + locale + region derivation
- `ad4e6a7` feat(identity): full bounded context — auth + JWT + OAuth + OTP + GDPR

## [Sprint 1] 2026-05-30 → 2026-05-31 — Scaffolding + audit + seed + migration 0001

- `20dc9fa` feat(scripts): generate_snacks.py — nutrition generator orchestrator (not executed)
- `dcd7227` feat(scripts): compute_embeddings.py — OpenAI text-embedding-3-large backfill
- `fc83bec` feat(scripts): seed_recipes.py — ingest cleaned catalog (2000 recipes)
- `3f1cb4d` feat(scripts): seed_foods.py — USDA starter dataset (~80 foods)
- `5aa3304` feat(migration): 0001_init.py — full schema (33 tables + enums + indexes + triggers + seed)
- `b9fca03` chore(data): run audit on seed catalog, save cleaned.json + report
- `55c1f8c` feat(scripts): audit_catalog.py with 8 gates + lexicon + --apply-fixes
- `4bad582` feat(scaffold): app/ skeleton with 9 bounded contexts + shared VOs + imaging compressor
- `d942ad6` feat(scaffold): pyproject + Dockerfiles + compose Hostinger-tuned for 8GB/2vCPU

## [Sprint 0] 2026-05-30 — Spec + ADRs + agents + EN-canonical reversion + multi-region

- `8f4c6ff` chore(agents): nutrition generator → EN canonical output (round-3)
- `867372d` docs(adr): 0007 i18n strategy + 0008 multi-region catalog
- `72da540` fix(spec): revert ES → EN canonical + i18n + multi-region (round-3)
- `ec746b6` docs(product): elite meal planning strategy — catalog × AI
- `b1664fa` docs(spec): catalog cleanup backlog tracking (§22.5)
- `820dd11` chore(agents): purge Qdrant from architects + update nutrition generator + QA macro tolerance
- `1da5ee3` fix(spec): consistency sweep across round-2 partial/not-fixed originals
- `c39b4f8` feat(spec): add coach SSE cleanup, prompt sha, cancel-deletion, progress_photos
- `3534527` fix(spec): close QA pass-2 BLOCKs — allergens trigger DDL + GDPR cascade chain
- `ef5f385` docs(spec): catalog ingest cleanup pipeline design
- `4db4ad6` chore(agents): reconcile architects to pgvector (drop Qdrant/Pinecone)
- `4db84d6` docs(spec): apply QA pre-implementation review fixes
- `5d46c04` docs(adr): foundational ADRs 0001-0005 for nutrition/security/cost decisions
- `0f386d2` chore(agents): add nova-qa-elite QA architect agent
- `1fa15f1` docs: NOVA backend design spec + arch agents
