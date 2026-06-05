# NOVA Nutrition — Backend

Python 3.12 + FastAPI + Postgres/Timescale + pgvector + Redis + Arq.

Tuned for the **Hostinger KVM 2** VPS baseline (8 GB RAM / 2 vCPU / 100 GB
NVMe). Container resource budget sums to 5.5 GB (db 3 GB + worker 1.5 GB +
api 0.6 GB + redis 0.4 GB) leaving ≈ 1.8 GB headroom for OS + Dokploy +
Traefik + spikes. See `docs/superpowers/specs/2026-05-30-nova-backend-design.md` §23.

## Quickstart (local)

```bash
cp .env.example .env
docker compose up --build
# api → http://localhost:8000
# /docs (OpenAPI), /healthz, /readyz, /metrics
docker exec -it nova-api alembic upgrade head
docker exec -it nova-api python -m scripts.seed_foods
docker exec -it nova-api python -m scripts.seed_recipes
docker exec -it nova-api python -m scripts.seed_i18n
```

## Native dev

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload
uv run alembic upgrade head
```

## Tests

```bash
uv run pytest                  # unit + nutrition + i18n
uv run pytest -m integration   # requires Docker for testcontainers
uv run pytest --cov=app --cov-report=term-missing
```

Load testing (manual, not in CI):

```bash
k6 run -e BASE_URL=https://api.ms-tech-stack.cloud -e TOKEN=… \
       tests/load/k6_baseline.js
```

## Bounded contexts (9 of 9)

| Context        | Purpose                                              |
|----------------|------------------------------------------------------|
| identity       | Auth, JWT, OAuth (Apple/Google), OTP, GDPR/LGPD     |
| profile        | User profile, locale, region derivation             |
| nutrition      | Mifflin-St Jeor, TDEE, macros, recalibration        |
| recipes        | Hybrid trigram + pgvector search, dynamic composition |
| plan           | 4-layer plan generation (eligibility → balance → rank → LLM coherence) |
| tracking       | Food/water/weight/fasting/progress logs + daily totals |
| grocery        | Plan-derived shopping lists, scaling, sharing       |
| gamification   | Streaks, 32-achievement catalog, levels, leaderboard |
| coach          | 4-camino router, intent classifier, SSE, proactive nudges |
| vision         | gpt-4o photo analyses, 2-tier cost optimisation     |
| voice          | Whisper STT, NLP food parser                        |
| notifications  | FCM scaffold (iOS/Android), mobile-only             |
| billing        | Stripe + Mercado Pago, entitlements, webhooks       |

## Catalog audit (before any seed)

```bash
uv run python scripts/audit_catalog.py \
  data/meals/nova_meals_catalog.json \
  --apply-fixes \
  --output data/meals/nova_meals_catalog.cleaned.json \
  --report reports/audit_$(date -u +%Y%m%dT%H%M%SZ).json
```

Gates documented in `docs/superpowers/specs/2026-05-30-catalog-ingest-pipeline.md`.

## Repo layout

```
app/<context>/{domain,application,infrastructure,presentation}/
worker/main.py        Arq tasks
migrations/versions/  Alembic (0001 init → 0006 billing)
scripts/              audit_catalog, seed_foods, seed_recipes,
                      seed_i18n, backup.sh, restore.sh
docker/               api.Dockerfile, worker.Dockerfile, db.Dockerfile, init.sql
docs/adr/             ADRs (0001 vocabulary, 0007 i18n, 0008 multi-region, …)
docs/ops/             backup + deploy runbooks
docs/architecture/    CONTEXT.md domain language glossary
docs/qa/              QA pre-launch reviews
docs/superpowers/     specs
tests/                unit / integration / contract / e2e / nutrition /
                      security / compliance / perf / i18n / data / load
```

## Architecture

Modular monolith, Clean Architecture + DDD per bounded context. Identifiers
are **EN canonical** snake_case throughout (Postgres ENUMs, JSON keys);
display strings live in `i18n_translations` keyed by canonical id × locale
(see ADR-0007). Multi-region recipe catalog via `recipes.regions[]`
(ADR-0008).

Polyglot persistence:

- **PostgreSQL** for transactional truth (users, recipes, foods, plans)
- **TimescaleDB** hypertables for biometric/intake time series
- **pgvector** HNSW indexes for semantic search (m=32, ef_construction=200) —
  no Qdrant/Pinecone (ADR-0005)
- **Redis** for sessions, idempotency, hot caches, leaderboards, celebration queues

## Cost projection

OpenAI cost cap is enforced at **$1.50 / user / day** (ADR-0004) by
`app.core.cost_cap` middleware on every OpenAI client. Vision pipeline is
2-tier (cheap model first, escalation only on low confidence). Current
projection for an average user with daily plan + 3 photos + 2 coach turns +
1 voice log: **≈ $0.11 / day** (≈ 7% of cap).

## Deploy

Hostinger + Dokploy: `docs/ops/runbook-deploy-hostinger-dokploy.md`.
Backup & recovery: `docs/ops/runbook-backup-recovery.md`.

## Links

- Domain language: `docs/architecture/CONTEXT.md`
- ADRs: `docs/adr/`
- Pre-launch QA: `docs/qa/2026-06-pre-launch-review.md`
- Main spec: `docs/superpowers/specs/2026-05-30-nova-backend-design.md`
