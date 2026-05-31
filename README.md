# NOVA Nutrition — Backend

Python 3.12 + FastAPI + Postgres/Timescale + pgvector + Redis + Arq.

Tuned for the **Hostinger KVM 2** VPS baseline (8 GB RAM / 2 vCPU / 100 GB
NVMe). Container resource budget sums to 5.5 GB (db 3 GB + worker 1.5 GB +
api 0.6 GB + redis 0.4 GB) leaving ≈ 1.8 GB headroom for OS + Dokploy +
Traefik + spikes. See `docs/superpowers/specs/2026-05-30-nova-backend-design.md` §23.

## Quickstart (local)

Prereqs: Docker + Docker Compose; optionally `uv` for native Python.

```bash
cp .env.example .env
docker compose up --build
# api → http://localhost:8000
# /docs (OpenAPI) /healthz /readyz /metrics
```

## Native dev

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload
```

## Tests

```bash
uv run pytest                  # unit + clinical + i18n
uv run pytest -m integration   # requires Docker for testcontainers
```

## Catalog audit (run before any seed)

```bash
uv run python scripts/audit_catalog.py \
  data/meals/nova_meals_catalog.json \
  --apply-fixes \
  --output data/meals/nova_meals_catalog.cleaned.json \
  --report reports/audit_$(date -u +%Y%m%dT%H%M%SZ).json
```

Gates are documented in `docs/superpowers/specs/2026-05-30-catalog-ingest-pipeline.md`.

## Repo layout

```
app/<context>/{domain,application,infrastructure,presentation}/
worker/main.py     Arq tasks
migrations/        Alembic
scripts/           audit_catalog, seed_foods, seed_recipes, compute_embeddings
docker/            api.Dockerfile + worker.Dockerfile + db.Dockerfile + init.sql
docs/adr/          ADRs (0001 vocabulary, 0007 i18n, 0008 multi-region, …)
docs/superpowers/  specs
tests/             unit / integration / contract / e2e / clinical / security / compliance / perf / i18n / data
```

## Architecture

Modular monolith, Clean Architecture + DDD per bounded context. Identifiers
are **EN canonical** snake_case throughout (Postgres ENUMs, JSON keys);
display strings live in `i18n_translations` keyed by canonical id × locale
(see ADR-0007). Multi-region recipe catalog via `recipes.regions[]`
(ADR-0008).
