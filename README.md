# NOVA Nutrition — Backend

Python 3.12 + FastAPI + Postgres/Timescale + pgvector + Redis + Arq.

VPS: Hostinger 1544011 — 15 GiB RAM / 2 vCPU / 193 GB NVMe. Deploy via Dokploy.

## Quickstart (local)

```bash
cp .env.example .env
docker compose up --build
# api → http://localhost:8000
# /docs (OpenAPI), /healthz, /readyz, /metrics
docker exec -it nova-api alembic upgrade head
docker exec -it nova-api python -m scripts.seed_foods
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
.venv/bin/python -m pytest tests/unit/ -q          # unit suite (1848+ tests)
.venv/bin/python -m pytest -m integration          # requires Docker/testcontainers
.venv/bin/python -m pytest --cov=app --cov-report=term-missing
# Vision golden set (28 LATAM images, needs OPENAI_API_KEY):
RUN_GOLDEN_SET=true .venv/bin/python -m pytest tests/eval -m eval -v
```

## Bounded contexts

| Context | Purpose |
|---|---|
| identity | Auth, JWT, OAuth (Apple/Google), OTP, GDPR/LGPD |
| profile | User profile, locale, region derivation |
| nutrition | Mifflin-St Jeor, TDEE, macros, recalibration |
| recipes | Hybrid trigram + pgvector search |
| plan | 4-layer pipeline (eligibility → shortlist → rank → LLM coherence) |
| tracking | Food/water/weight/fasting logs + daily totals |
| grocery | Plan-derived shopping lists |
| gamification | Streaks, 32-achievement catalog, levels, leaderboard |
| coach | Intent classifier, SSE, proactive nudges |
| vision | Two-pass gpt photo analysis (identify → estimate, K=3 median) |
| voice | Whisper STT, NLP food parser |
| notifications | FCM (iOS/Android) |
| billing | Stripe + Mercado Pago, entitlements |

## Architecture

Modular monolith, Clean Architecture + DDD per bounded context. Identifiers are **EN canonical** snake_case throughout; display strings in `i18n_translations` keyed by canonical id × locale (ADR-0007). Multi-region recipe catalog via `recipes.regions[]` (ADR-0008).

- **PostgreSQL** — transactional truth
- **TimescaleDB** hypertables — biometric/intake time series
- **pgvector** HNSW (m=32, ef_construction=200) — semantic search, no Qdrant/Pinecone (ADR-0005)
- **Redis** — sessions, idempotency, hot caches, leaderboards

## Catalog

PROD: 956 recipes across 4 meal slots. Source of truth: DB.

## Deploy

Dokploy + Hostinger. Push → container rebuild → `alembic upgrade head` auto.
