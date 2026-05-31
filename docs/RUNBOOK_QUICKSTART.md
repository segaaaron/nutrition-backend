# NOVA Backend Quickstart

## Run Local (5 min setup)

```bash
# 1. Configure env
cp .env.example .env
# Edit .env and set at minimum:
#   OPENAI_API_KEY=sk-...
#   JWT_SECRET=<random 32-byte hex>
#   STRIPE_SECRET_KEY=sk_test_...        # optional for non-billing tests
#   MERCADOPAGO_ACCESS_TOKEN=TEST-...    # optional

# 2. Start stack
docker compose up -d

# 3. Run migrations
docker compose exec api alembic upgrade head

# 4. Seed catalog + i18n
docker compose exec api python scripts/seed_foods.py
docker compose exec api python scripts/seed_recipes.py
docker compose exec api python scripts/seed_i18n.py

# 5. Health check
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# 6. Open Swagger UI
open http://localhost:8000/docs
```

## Smoke Test Endpoints

```bash
BASE=http://localhost:8000

# Health
curl -s $BASE/healthz | jq .
curl -s $BASE/readyz  | jq .

# Auth — OTP request (replace email)
curl -s -X POST $BASE/v1/auth/otp/request \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com"}'

# Recipes search
curl -s "$BASE/v1/recipes/search?q=avena&locale=es-PE&region=PE" | jq '.results[0]'

# Plan create (requires JWT — capture from OTP verify response)
TOKEN="<paste JWT>"
curl -s -X POST $BASE/v1/plans \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"days":7,"target_kcal":2200}' | jq .

# Coach SSE
curl -N -H "Authorization: Bearer $TOKEN" \
  "$BASE/v1/coach/stream?msg=hola"
```

## Common Commands

```bash
# View logs
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f postgres

# Shell into API
docker compose exec api bash

# Run tests
docker compose exec api pytest -x
docker compose exec api pytest tests/clinical -v
docker compose exec api pytest tests/coach -v

# Create new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Stop and clean
docker compose down                # keep volumes
docker compose down -v             # nuke volumes (DESTROYS DATA)

# Backup / restore
bash scripts/backup.sh
bash scripts/restore.sh <dump.sql.gz>

# One-shot snack catalog generation (~$3 OpenAI spend)
docker compose exec api python scripts/generate_snacks.py

# Catalog audit
docker compose exec api python scripts/audit_catalog.py
docker compose exec api python scripts/audit_catalog.py --apply-fixes
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/readyz` returns 503 | Redis or Postgres not up | `docker compose ps` — restart missing container |
| Alembic "Can't locate revision" | Volume drift after schema change | `docker compose down -v && docker compose up -d && alembic upgrade head` (dev only) |
| OpenAI 429 | Rate limit on free key | Wait or upgrade tier; circuit breaker will pause for 60s |
| Recipe search returns empty | i18n + region filter too strict | confirm `seed_i18n.py` ran; try `region=US` |
| Coach SSE drops at 30s | Proxy idle timeout | use nginx `proxy_read_timeout 1h;` in Dokploy template |
| `pyvips` import error in container | libvips missing in custom image | rebuild API image — `docker compose build api` |
| High RAM on Postgres | shared_buffers too high | reduce in `docker/postgres.conf` to 768MB |
| MercadoPago webhook 401 | HMAC validation lenient/strict mismatch | check `MP_WEBHOOK_SECRET` in `.env`; tracked as pending hardening |

## Deploy to Hostinger via Dokploy

Full procedure: `docs/ops/runbook-deploy-hostinger-dokploy.md`. Backup procedure: `docs/ops/runbook-backup-recovery.md`.
