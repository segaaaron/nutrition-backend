# Session Handoff — 2026-06-03

> **Audience:** next AI assistant or owner picking up the work.
> **Branch:** `main` (master is DEAD, never use it)
> **Status:** working tree has 50+ modified files, sin commit. Owner to commit.

## Session goals achieved

1. **STT removed from backend.** Whisper deleted. Device transcribes via iOS `SFSpeechRecognizer` / Android `SpeechRecognizer`. Transcript posted to existing `/logs/food/text` endpoint. Cost: $0/min.
2. **Vision pipeline overhaul** with 4-layer cost strategy: prefilter + cache + cascade + rate limit.
3. **Backend hardening:** 38 → 126 vision tests, 0 → 92.72% router coverage, mypy/ruff clean on all touched files.
4. **Dev workflow automated:** Docker entrypoint auto-applies Alembic migrations; Makefile + scripts/db_change.py for guided schema changes.
5. **Source-traced thresholds** in nutrition + plan domain (ADA, KDOQI, ACOG, IOM, FAO/WHO, Mifflin 1990, etc).
6. **Algorithm audit** identified vaporware in agent prompts vs real code.
7. **Scope reaffirmation:** all "nutrition guidance" / "disclaimer" / "mobile UI" framing removed from backend.
8. **Branch policy locked:** main only. Master dead.

## Files in working tree (50+ modified, 13 new)

### Application code modified
- `app/voice/presentation/router.py` — removed POST /logs/food/voice
- `app/voice/infrastructure/whisper_client.py` — DELETED
- `app/vision/infrastructure/openai_vision.py` — cascade + prefilter + auto detail + max_tokens cap + prompt_sha
- `app/vision/application/process_vision_job.py` — cache + SETNX lock + per-user rerun + prompt invalidation
- `app/vision/application/submit_photo.py` — prefilter gate
- `app/vision/application/reconcile_with_plan.py` — type hints
- `app/vision/infrastructure/repositories.py` — `find_recent_completed_by_sha` + `_strip_personal_fields`
- `app/vision/infrastructure/food_matcher.py` — source-traced noqa
- `app/vision/infrastructure/models.py` — pgvector type ignore justified
- `app/vision/infrastructure/redis_notifier.py` — type hints
- `app/vision/domain/ports.py` — `is_food_image()`, `current_prompt_sha256()` ports + `ConditionGate` doc reframed
- `app/vision/domain/events.py` — type hints
- `app/vision/presentation/router.py` — provider injection + `response_model=None` fix
- `app/core/config.py` — settings cascade + prefilter + Redis pool + STT removed + scope reframe
- `app/core/cost_cap.py` — pipeline 3→1 RTT + Decimal helpers
- `app/core/redis.py` — explicit ConnectionPool 50 conn
- `app/core/metrics.py` — 5 new Prometheus counters + type hints
- `app/nutrition/domain/macro_partitioning.py` — bug fix trim loop + Decimal tolerance
- `app/nutrition/domain/mifflin_st_jeor.py` — source-trace
- `app/nutrition/domain/hydration.py` — source-trace
- `app/nutrition/domain/recalibration.py` — source-trace
- `app/plan/domain/bmr_safety.py` — source-trace + Mifflin/Cunningham/FAO/AND
- `app/plan/domain/macro_calculator.py` — source-trace Helms/Morton/Phillips/IOM/ISSN
- `app/plan/domain/condition_gates/*.py` — source-trace ADA/KDOQI/ACOG/IOM/ACC-AHA/WHO + scope reframe
- `app/plan/application/layer1_eligibility.py` — source-trace + scope reframe
- `app/shared/domain/macro_tolerance.py` — Decimal-only + scope reframe
- `app/profile/presentation/schemas.py` — scope reframe (removed UI references)
- `docker/api.Dockerfile` — ENTRYPOINT entrypoint.sh + healthcheck start_period 30s
- `docker-compose.yml`, `docker-compose.mvp.yml` — cleaned alembic duplication
- `.env.example` — vision cascade + prefilter + Redis pool vars + STT removed
- `CLAUDE.md` — GR#2 branch policy + GR#3 scope + session log

### Files created
- `migrations/versions/0011_vision_jobs_sha_idx.py` — partial CONCURRENT index
- `app/vision/presentation/rate_limit.py` — Redis sliding window 30/hour
- `docker/entrypoint.sh` — auto `alembic upgrade head` pre uvicorn
- `Makefile` — db.*, test.*, lint, format, run, worker, docker.* targets
- `scripts/db_change.py` — guided schema change wizard
- `docs/adr/0021-vision-cascade-prefilter.md` — this decision recorded
- `docs/handoff/2026-06-03-vision-pipeline-session.md` — this file

### Tests created (78 new)
- `tests/unit/vision/test_value_objects.py` (Confidence + property)
- `tests/unit/vision/test_get_job_status.py` (happy/NotFound/BOLA)
- `tests/unit/vision/test_learn_user_correction.py` (norm + property)
- `tests/unit/vision/test_reconcile_with_plan.py` (delta_pct)
- `tests/unit/vision/test_redis_notifier.py` (channel + UUID)
- `tests/unit/vision/test_schemas.py` (Pydantic defaults)
- `tests/unit/vision/test_food_matcher.py` (precedence)
- `tests/unit/vision/test_repositories.py` (JSONB roundtrip + PII strip)
- `tests/unit/vision/test_router_endpoints.py` (22 contract tests)
- `tests/unit/vision/test_cost_cap_pricing.py`
- `tests/unit/vision/test_cache_cross_user.py`
- `tests/unit/vision/test_race_condition.py`
- `tests/unit/vision/test_truncated_json.py`
- `tests/unit/vision/test_cascade_disabled.py`
- `tests/unit/vision/test_redis_outage.py`
- `tests/unit/vision/test_failure_path.py`
- `tests/unit/vision/test_prefilter_*.py` (6 files)
- `tests/unit/plan/test_allergen_invariant.py` (Hypothesis 200 examples)
- `tests/unit/plan/test_multi_condition.py` (combo matrix)
- `tests/unit/nutrition/test_macro_invariants.py` (protein floor/AMDR/closure)
- `tests/unit/core/test_cost_cap_pipeline.py`
- `tests/unit/core/test_redis_pool.py`
- `tests/integration/vision/conftest.py` + 4 integration test files (Docker required)

## Verification state at session end

```
git branch              → main
git status (modified)   → 50 files
Tests unit + nutrition  → 598 passed, 2 skipped (no OpenAI key, no perf flag)
Tests integration       → 8 skipped (Docker required)
Coverage vision         → 92.72%
mypy strict touched     → 0 errors
ruff touched            → 0 issues
Stashes                 → 1 dangling stash@{0} from previous protocol violation
```

## Owner action items (in priority order)

### 🔴 Pre-deploy

1. `git stash show -p stash@{0}` — inspect dangling stash
2. `git stash drop stash@{0}` — drop if safe (it predates session)
3. Add `python-multipart` to `pyproject.toml [project.optional-dependencies].dev`
4. Commit changes (suggested 5 atomic commits below)
5. `git push origin main`

### 🔴 Deploy

6. Dokploy `.env` updates:
   - DELETE `OPENAI_STT_MODEL=whisper-1`
   - ADD `VISION_CASCADE_ENABLED=false`
   - ADD `VISION_MAX_OUTPUT_TOKENS=1200`
   - ADD `VISION_FOOD_PREFILTER_ENABLED=true`
   - ADD `REDIS_MAX_CONNECTIONS=50`
7. ROTATE `OPENAI_API_KEY` (was exposed twice in chat during session — already done per owner confirmation)
8. Re-deploy Dokploy → docker/entrypoint.sh auto-applies migration 0011
9. Smoke test `POST /logs/food/photo` (prefilter active, cascade off)

### 🟡 Decisions (no rush)

10. Pricing freemium (Fitia ref: $19.99/$59.99/$89.99 — undercut suggested)
11. Photo in free tier: 0 / 3-day / unlimited
12. Consolidate duplicate Mifflin implementations (`app/nutrition/` vs `app/plan/bmr_safety.py`)
13. Layer 1 CKD f-string `f"...{ckd_cap}"` → bind param (future-proof SQL injection)
14. Wire or delete `reconcile_with_plan` use case (no HTTP endpoint exists)
15. Add HTTP `Retry-After` header on 429 responses
16. Cleanup vaporware claims in `nova-nutrition-algorithms-expert` agent prompt (Pareto, Kalman, PELT, NSGA-II, bioavailability — none exist in code)

### 🟡 Pre-cascade-flip blockers

17. Build golden set (≥100 photos LatAm + US + EU with ground truth) — owner annotates or iOS beta opt-in
18. Eval script mini vs gpt-4o full against golden set
19. Calibrate confidence threshold (currently 0.7 placeholder)
20. Shadow-run 1 week minimum before flipping `VISION_CASCADE_ENABLED=true`

## Suggested commit sequence (atomic, owner executes)

```bash
# 1. Voice cleanup
git add app/voice/ .env.example app/core/config.py
git commit -m "feat(voice): remove backend STT, delegate to device

iOS SFSpeechRecognizer / Android SpeechRecognizer transcribe locally.
Backend receives text via existing POST /logs/food/text.
Whisper API and OPENAI_STT_MODEL env removed. Cost: \$0/min STT."

# 2. Vision pipeline
git add app/vision/ app/core/cost_cap.py app/core/redis.py \
        app/core/metrics.py app/core/config.py \
        tests/unit/vision/ tests/unit/core/ \
        tests/integration/vision/ \
        migrations/versions/0011_vision_jobs_sha_idx.py
git commit -m "feat(vision): hybrid cascade + food prefilter + SHA cache

4-layer cost strategy (ADR-0021):
  L0 prefilter rejects supplements/water/non-food (gpt-4o-mini detail:low)
  L1 SHA256 cache with PII strip + per-user matcher rerun
  L2 gpt-4o-mini primary (default OFF until golden-set calibration)
  L3 gpt-4o fallback on low confidence

Plus rate limit 30/hour/user, Redis SETNX inflight lock, Pillow off
event loop, JSONDecodeError graceful fallback, cost cap pipeline 3->1 RTT,
explicit Redis pool 50 conn. Projected savings 81.8% (flag flip pending
golden set). 126 vision tests, 92.72% coverage."

# 3. Nutrition + plan
git add app/nutrition/ app/plan/ app/shared/ app/profile/ \
        tests/unit/nutrition/ tests/unit/plan/
git commit -m "feat(plan): source-traced thresholds + safety invariant tests

Annotate all condition gates with peer-reviewed source (ADA 2024, KDOQI 2020,
ACOG 234, IOM DRI, FAO/WHO/UNU 2001, Mifflin 1990, etc).

Add hypothesis property tests for allergen hard-block invariant (200 examples),
multi-condition composition (diabetes_t2 + ckd + pregnancy combos), and
macro partitioning invariants (protein floor, fat AMDR, closure).

Fix macro_partitioning trim loop for low-kcal + high-protein cases and
Decimal-only tolerance comparison (was failing 2 tests due to float ULP)."

# 4. Tooling
git add docker/ docker-compose.yml docker-compose.mvp.yml \
        Makefile scripts/db_change.py
git commit -m "build: auto-apply alembic + dev workflow tooling

docker/entrypoint.sh runs alembic upgrade head on every container boot.
Idempotent. Owner no longer runs migrations manually.

Makefile shortcuts: db.new, db.upgrade, db.downgrade, db.history, db.check,
test.*, lint, typecheck, format, run, worker.

scripts/db_change.py: guided interactive schema change wizard with diff
preview + review checklist + confirm before applying."

# 5. Docs + scope
git add CLAUDE.md docs/
git commit -m "docs: ADR-0021 vision cascade + session 2026-06-03 handoff

Plus CLAUDE.md GR#2 (branch policy: main only) and GR#3 (scope: backend
nutrition tracker only, no frontend / no medical advice / no supplements
in catalog). Session decisions log appended."

# 6. Push
git push origin main
```

## Branch policy reminder

**`master` is DEAD.** Future AI sessions:
- At start, run `git branch --show-current`
- If `master` → ALERT owner before editing
- If `main` → proceed

Owner enforces. Pre-commit hook optional.

## Vaporware in agent prompts (cleanup pending)

`nova-nutrition-algorithms-expert` agent prompt claims these algorithms but **no code exists**:
- Pareto / NSGA-II multi-objective
- Kalman smoothing weight series (real: OLS winsorised)
- PELT change-point plateau detection (real: slope threshold)
- Adherence prediction logistic (real: passthrough completion_rate)
- Bioavailability iron heme/non-heme, calcium oxalates
- Katch-McArdle BMR
- B12 weekly check, Omega-3 EPA+DHA targets
- Variety cosine on 1536-dim embedding (real: Jaccard set distance)
- Dynamic TDEE wearable integration
- Adaptive thermogenesis `−7% × log(days/14)` (real: blend OLS)

Decision pending: remove claims OR ticket implementation.

## Industry pricing reference (2026-06)

| App | Monthly | Annual | Family/yr | Photo tier |
|---|---|---|---|---|
| Fitia | $19.99 | $59.99 | $89.99 | Premium only, no free |
| MyFitnessPal | $9.99 | $79.99 | — | Passio SDK, premium |
| Yazio | $7.99 | ~$50 | — | Premium |
| Lifesum | $4.16 (eq) | $49.99 | — | Premium, slow |

NOVA pricing suggestion: undercut Fitia, $9.99/mo or $49.99/yr, family $79.99. Photo free tier 3/day with premium unlimited. Owner decides.

## Contact

Owner: Miguel Ángel Saravia · mikisaraviaios@gmail.com
