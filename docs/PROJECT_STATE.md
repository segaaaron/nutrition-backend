# Project State Snapshot

## Last Updated
2026-06-04

## Status — Closed-Beta GO (2026-06-03)

**Verdict:** GO for PROD closed-beta (≤100 users). QA approved Sprint 1+2+3 + bug-fix sprint.

**Test suite:** 684+ unit tests pass / 3 env-gated skipped. 0 failures.

**Algorithm coverage (property-based + invariant):**
- Property-based tests for BMR, TDEE, macro back-adjust, recalibration, intake bias, AT, hydration thresholds
- Multi-condition composite invariants property-tested
- Mutation testing tooling (mutmut) removed 2026-06-03: low ROI for solo-dev + pre-revenue. Historical baseline preserved in `docs/archive/mutation_baseline_sprint3.md`. Confidence now relies on hypothesis property tests + local ErrorTracker (ring buffer + JSONL) production error tracking.

**Security hardened:**
- SQL bind params throughout (0 injection vectors)
- Catalog fail-closed for diabetes_t2 / hypertension / hypercholesterolemia / ckd
- Retry-After RFC 6585 on 429/503
- Idempotency-Key required on /plans, /logs/food/text, /logs/food/photo
- Prompt injection delimiters + sanitizer in coach
- Audit log immutability tests + GRANT REVOKE
- PII log grep gate (`scripts/pii_log_grep.py`)
- Advisory lock + partial unique index on recalibration
- MercadoPago webhook HMAC strict (sha256 + ts ±300s + `hmac.compare_digest`, fail-closed when secret missing)

### Remaining blockers for PROD general (>1k users)

Closed-beta launch readiness: **GO**. All PROD-scaling items have explicit status + activation trigger. None block closed-beta (≤100 users).

| Item | Status | Trigger to activate |
|---|---|---|
| #1 Perf baselines k6 + CI gate >15% | **SCRIPTS READY** (`tests/load/k6_*.js`) | requires staging env to run |
| #2 AI eval golden set ≥100 platos | **SCAFFOLD READY** (`docs/qa/golden_set/` schema + 5 samples) | manual curation + `_invoke_vision_pipeline` wire |
| #3 k6 staging load tests | **DEFERRED** | requires staging env (single-env Dokploy) |
| #4 S0-residual security backlog | **FROZEN** | auto-trigger ≥100 paying users per CLAUDE.md |
| #5 Structured logs audit prod | **DEFERRED** | requires prod deployment + log aggregation |

Scripts entregados (#30): `tests/load/k6_baseline_smoke.js`, `tests/load/k6_steady_100rps_10m.js`, `tests/load/k6_spike_500rps_30s.js`, `tests/load/README.md`. Makefile targets: `load-smoke`, `load-steady`, `load-spike`.

Scaffold entregado (#31): `docs/qa/golden_set/{README.md, schema.json, sample_entries.json}`, `tests/eval/test_vision_pipeline_eval.py` (marker `eval`, gated por `RUN_GOLDEN_SET=true`).

### Closed-beta launch conditions

- Block onboarding `conditions in {ckd, chf}` until R8 wired fully verified prod
- Monitor `recalibration_concurrent_conflict` WARN log for 7 days
- Local ErrorTracker + /healthz + /readyz + Prometheus counters verified live
- Mobile SDK regenerated for D12 breaking changes (Idempotency-Key required on plan + food endpoints)

### Mobile SDK breaking changes (D12)

| Endpoint | Header required |
|---|---|
| POST /v1/plan/generate | Idempotency-Key UUIDv4 |
| POST /v1/plan/me/recalibrate | Idempotency-Key UUIDv4 |
| POST /v1/plan/me/swap/{id} | Idempotency-Key UUIDv4 |
| POST /v1/logs/food/text | Idempotency-Key UUIDv4 |
| POST /v1/logs/food/photo | Idempotency-Key UUIDv4 |

Coach `/chat` does NOT support Idempotency-Key (LLM responses non-idempotent by nature, RFC 9110 §9.2.2).

## Operational Status

- Backend MVP code **COMPLETE**
- Branch policy: `main` only (master DEAD per CLAUDE.md GR#2)
- Pending: owner to commit 50+ working tree changes from session 2026-06-03
- Pending: Dokploy `.env` update + redeploy → auto-apply migration 0011
- Pending: golden set calibration → flip `VISION_CASCADE_ENABLED=true`

## Statistics (post session 2026-06-03)

| Metric | Value |
|---|---|
| Bounded contexts | 12 |
| Alembic migrations | 11 (0001 → 0011) |
| ADRs | 21 (0001 → 0021) |
| REST + SSE endpoints | 30+ |
| Test cases | 598 passed + 8 integration (Docker-gated) |
| Vision coverage | 92.72% |
| mypy strict touched files | 0 errors |
| ruff touched files | 0 issues |
| Active conditions | lactation, diabetes_t2, ckd, pregnancy, hypertension, celiac |
| Blocked conditions | diabetes_t1 |
| Blocked regions | us |

## Directory Tree (current, depth 3)

```
.
├── .claude/
│   └── agents/                    (4 specialist agent prompts)
├── app/                           (12 bounded contexts, each with application/domain/infrastructure/presentation)
│   ├── billing/
│   ├── coach/
│   ├── core/
│   ├── gamification/
│   ├── grocery/
│   ├── identity/
│   ├── imaging/
│   ├── notifications/
│   ├── nutrition/
│   ├── plan/
│   ├── profile/
│   ├── recipes/
│   ├── shared/
│   ├── tracking/
│   ├── vision/
│   ├── voice/
│   └── main.py
├── data/
│   └── meals/                     (seed recipe payloads)
├── docker/                        (Dockerfile + compose pieces)
├── docs/
│   ├── adr/                       (0001 → 0008)
│   ├── architecture/CONTEXT.md
│   ├── ops/                       (backup + dokploy runbooks)
│   ├── product/                   (meal planning strategy)
│   ├── qa/                        (pre/post/pre-launch reviews + golden set)
│   └── superpowers/specs/
├── migrations/versions/           (0001_init → 0006_billing)
├── reports/                       (audit output, cleaned catalog)
├── scripts/                       (audit, seed, embeddings, generate_snacks, backup, restore, resolve_ingredients)
├── tests/                         (nutrition, compliance, contract, e2e, i18n, integration, load, perf, security, unit)
├── worker/                        (Arq tasks)
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
├── .env.example
└── README.md
```

## Bounded Contexts Status

| Context | Status | Notes |
|---|---|---|
| identity | DONE | JWT + OAuth (Google, Apple) + OTP email + GDPR erasure |
| profile | DONE | locale + region derivation, allergens, conditions |
| nutrition | DONE | Mifflin + TDEE + macros + recalibration (ADR-0002) |
| recipes | DONE | hybrid search (trigram + pgvector HNSW) + i18n |
| plan | DONE | 4-layer pipeline L1→L4, Redis 24h cache on L4 |
| vision | DONE | photo upload + gpt-4o vision pipeline + parser |
| voice | DONE | whisper STT + NLP food parser + text quick-log |
| coach | DONE | 4-camino router + SSE + proactive features A-G |
| tracking | DONE | food_log query, water, weight (Timescale), fasting, progress photos |
| grocery | DONE | generate / scale / share / categorize |
| gamification | DONE | achievements, streaks, levels, leaderboard (flag-gated) |
| billing | DONE | Stripe + Mercado Pago + gateway router by country |
| notifications | DONE | FCM (iOS/Android) — Web Push removed 2026-06-04, no PWA scope |
| core / shared / imaging | DONE | config, logging, DI, errors, circuit breakers, cost cap, pyvips |

## Next Immediate Actions for User

Post session 2026-06-04 (owner-only actions, AI cannot perform per GR#0):

1. Commit current working tree (50+ files, multi sub-sessions: catalog cleanup, MP HMAC, ADR-0026 L1, Resend, Sentry purge, lifespan migration, etc.)
2. Rotate Resend API key (any key shared in prior chat history is now compromised)
3. Verify Resend domain `nova-nutrition.com` (DNS SPF/DKIM/DMARC records) — required for `no-reply@nova-nutrition.com` outbound
4. GitHub Settings toggles: secret scanning, push protection, Dependabot alerts (native — `dependabot.yml` removed)
5. Dokploy `.env` update + redeploy → entrypoint auto-applies migrations 0011 + 0013
6. Register `nova-nutrition.com` domain (Cloudflare/Namecheap) + point DNS to Hostinger KVM 2
7. App Store Connect record (future — required to flip FCM iOS path)

## Known Blockers

- FCM iOS deferred until App Store record exists
- Anti-cheat for leaderboard gated behind feature flag — leaderboard cannot ship live until abuse model exists. Design: **ADR-0026**. Status 2026-06-04: L1 + retention shipped behind sub-flag `leaderboard_l1_caps_enabled` (default OFF); L2 anomaly scorer Arq job shipped (cron 07:00 UTC = 02:00 Lima); L3 ZADD gate deferred (architectural ambiguity).
  - [x] Layer 1 caps in event handlers + new `gamification.infrastructure.anti_cheat_caps` (XP daily 500, text 150, photo 200, weight 30) + Redis counters
  - [x] Per-meal-slot food-log cap (3) in voice + vision pipelines, weight delta sanity (±2 kg/day or 5 % bw) in `LogWeight`
  - [x] Streak 20h minimum interval inside `_bump_streak` (kills 23:59→00:01 farming)
  - [x] Region immutability 30d inline in `UpdateProfile` + `profile_region_change_audit` table (migration 0013)
  - [x] Same-SHA256 XP suppression (24h window) using existing `vision_jobs.image_sha256` index
  - [x] pHash column on `vision_jobs` (migration 0013, nullable, no backfill — populated by deferred L2 worker)
  - [x] `gamification_shadow_ban` + `leaderboard_audit` tables (migration 0013, additive)
  - [x] Retention purge cron (`worker/leaderboard_audit_purge_task.py`, 180d horizon, 03:00 UTC)
  - [x] L2 Arq job `anomaly_score` — implemented (`worker/anomaly_score_task.py`), cron 07:00 UTC (02:00 Lima), 6 signals weighted 0-100, `score>=70` INSERTs `gamification_shadow_ban` (ON CONFLICT DO NOTHING idempotent via UNIQUE(user_id)), `40<=score<70` structured-log review flag, `<40` info log. Signals `social_density_ip` + `account_age_vs_rank` return `None` (no backing data) → weight redistributed across available signals. 36 unit + hypothesis property tests in `tests/unit/gamification/test_l2_anomaly_score.py`.
  - [ ] L3 shadow-ban ZADD gate — **DEFERRED** (architectural ambiguity: ADR-0026 assumes `app/gamification/application/award_xp.py` which does NOT exist; no ZADD write path is written anywhere in the codebase; the public leaderboard `ZREVRANGE`s from a key nobody writes). Implementing L3 requires (a) a new `award_xp` use case + canonical ZADD write path and (b) an ADR-0026.1 addendum defining score formula (`total_xp` vs `ZINCRBY` delta), period bucket key (ISO week vs rolling 7d), country source caching, TTL strategy, idempotency. Owner decision pending next session.
  - [ ] 7-day clean run of nightly L2 job in production (now unblocked; awaiting deploy)
  - [ ] Manual sock-puppet drill on staging passes (requires staging env)
  - [ ] Sentry alert on L2 cron failure (add after first scheduled run on staging)
  - [x] Owner SQL view skeleton at `docs/ops/anti_cheat_admin_queries.sql` (queries commented, awaiting L2/L3 activation)
  - [ ] Country whitelist (MX/AR/CL/PE/CO) + period whitelist (`week` only) wired into endpoint

## Pricing + Photo Tier (decided 2026-06-04)

| Tier | Price (USD) | Photos |
|------|-------------|--------|
| Free | $0 | 0 (post 7-day trial) |
| Trial (7d, auto on signup) | $0 | 3/day |
| Premium Monthly | $9.99/mo | Unlimited (cap $1.50/day per ADR-0004) |
| Premium Yearly | $39.99/yr (~$3.33/mo) | Unlimited |
| Family Yearly | $59.99/yr (≤4 users) | Unlimited per member |

Strategy: undercut Fitia 33-50% for LatAm-first traction. Stripe charges USD (USA/EU/CA/UK/AU); MercadoPago auto-converts to PEN/MXN/COP/CLP/ARS/BRL/UYU. Full doc + economics: `docs/product/pricing.md`. Re-evaluate at 1,000 paying users.

## Cost Projections

| Item | Cost |
|---|---|
| OpenAI per user / day (steady state) | $0.022 |
| OpenAI hard cap per user / day | $1.50 (ADR-0004) |
| Hostinger KVM 2 | included in existing plan |
| Cloudflare CDN/DDoS | $0 (free tier) |
| Domain | ~$12 / yr |
| Ops MVP total | ~$30 / mo |
| Snack catalog one-shot generation | ~$3 |
| Upgrade trigger | active users > 1,500 → Hetzner CX42 €13/mo |
