# Project State Snapshot

## Last Updated
2026-06-03

## Status — Closed-Beta GO (2026-06-03)

**Verdict:** GO for PROD closed-beta (≤100 users). QA approved Sprint 1+2+3 + bug-fix sprint.

**Test suite:** 684+ unit tests pass / 3 env-gated skipped. 0 failures.

**Algorithm coverage (property-based + invariant):**
- Property-based tests for BMR, TDEE, macro back-adjust, recalibration, intake bias, AT, hydration thresholds
- Multi-condition composite invariants property-tested
- Mutation testing tooling (mutmut) removed 2026-06-03: low ROI for solo-dev + pre-revenue. Historical baseline preserved in `docs/archive/mutation_baseline_sprint3.md`. Confidence now relies on hypothesis property tests + Sentry production error tracking.

**Security hardened:**
- SQL bind params throughout (0 injection vectors)
- Catalog fail-closed for diabetes_t2 / hypertension / hypercholesterolemia / ckd
- Retry-After RFC 6585 on 429/503
- Idempotency-Key required on /plans, /logs/food/text, /logs/food/photo
- Prompt injection delimiters + sanitizer in coach
- Audit log immutability tests + GRANT REVOKE
- PII log grep gate (`scripts/pii_log_grep.py`)
- Advisory lock + partial unique index on recalibration

### Remaining blockers for PROD general (>1k users)

1. Perf baselines k6 captured + CI regression gate >15% (defer: needs staging)
2. AI eval golden set ≥100 platos (vision + coach evaluation)
3. k6 load tests `steady_100rps_10m` + `spike_500rps_30s` green on staging
4. S0-residual security backlog (auto-trigger at ≥100 paying users per CLAUDE.md)
5. Sentry release tracking wired + structured logs audit (PII grep + retention policy verified in prod)

### Closed-beta launch conditions

- Block onboarding `conditions in {ckd, chf}` until R8 wired fully verified prod
- Monitor `recalibration_concurrent_conflict` WARN log for 7 days
- Sentry + observability dashboards live
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
| notifications | DONE | Web Push (VAPID) + FCM Android (iOS deferred) |
| core / shared / imaging | DONE | config, logging, DI, errors, circuit breakers, cost cap, pyvips |

## Next Immediate Actions for User

1. Bring local stack up: `docker compose up -d` (see `docs/RUNBOOK_QUICKSTART.md`)
2. Run `alembic upgrade head` inside the API container
3. Run seed scripts (`seed_foods.py`, `seed_recipes.py`, `seed_i18n.py`)
4. Smoke-test endpoints via `/docs` (FastAPI Swagger)
5. Manually resolve the 2 catalog duplicates flagged by `audit_catalog.py`
6. Run `python scripts/generate_snacks.py` (~$3 OpenAI)
7. Provision Dokploy on Hostinger KVM 2 (ID 1544011) — `docs/ops/runbook-deploy-hostinger-dokploy.md`
8. First deploy via Dokploy
9. Mobile app kickoff (separate repo)

## Known Blockers

- 2 catalog duplicates require manual resolution before snack generation
- FCM iOS deferred until App Store record exists
- MercadoPago webhook strict HMAC validation pending (currently lenient)
- Anti-cheat for leaderboard gated behind feature flag — leaderboard cannot ship live until abuse model exists
- Sentry + Grafana Cloud not wired (opt-in, not blocking)

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
