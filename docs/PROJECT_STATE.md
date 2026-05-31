# Project State Snapshot

## Last Updated
2026-05-31

## Status

- Backend MVP code **COMPLETE**
- Pending: deploy to local Docker stack, smoke-test, then migrate to Dokploy on Hostinger
- Pending: snack catalog generation, FCM iOS, mobile app, MercadoPago HMAC hardening

## Statistics

| Metric | Value |
|---|---|
| Git commits | 60 |
| Python LoC (excluding tests/cache) | ~18,810 |
| Bounded contexts | 12 |
| Alembic migrations | 6 (0001 → 0006) |
| ADRs | 8 (0001 → 0008) |
| REST + SSE endpoints | 30+ |
| Test cases | ~50 (unit + integration + clinical + e2e + load) |

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
├── tests/                         (clinical, compliance, contract, e2e, i18n, integration, load, perf, security, unit)
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
