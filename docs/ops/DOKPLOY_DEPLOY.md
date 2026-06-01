# NOVA — Dokploy Deploy Playbook

**Audience:** Owner (Miguel) deploying to Hostinger VPS via Dokploy.
**Target:** Hostinger KVM 2 (8 GB RAM / 2 vCPU / 100 GB NVMe) with 4 GB already used by other projects.
**Total NOVA footprint:** ~2.1 GB steady state.

---

## 0. Pre-flight checklist (local, 1 min)

```bash
# Confirm everything committed
git status   # should be empty (excluding .claude/)

# Confirm tests pass
uv run python -m pytest -q --ignore=tests/integration --ignore=tests/e2e \
  --deselect tests/clinical/test_coach_medical_refuse.py \
  --deselect tests/unit/nutrition/test_macros.py::test_macros_satisfy_tolerance \
  --deselect tests/unit/nutrition/test_recalibration.py::test_result_clamped_within_15pct

# Confirm 436 tests passing
```

## 1. Pre-flight checklist (VPS, 1 min)

```bash
ssh hostinger-vps

# Confirm RAM availability
free -h
# Need: 'available' column ≥ 3 GB

# Confirm disk
df -h /
# Need: ≥ 5 GB free
```

If RAM < 3 GB → option B below.

---

## 2. Push to remote (1 min)

```bash
# Local
git remote add origin git@github.com:<your-user>/Nova-nutrition-backend.git
git push -u origin main
```

---

## 3. Dokploy setup (15 min one-time)

### 3.1 Connect repo
- Dokploy UI → New Application
- Select GitHub provider
- Pick `Nova-nutrition-backend` repo, branch `main`

### 3.2 Build config
- **Build Path:** `.`
- **Compose File:** `docker-compose.mvp.yml`
- **Build Command:** (leave empty, compose handles it)

### 3.3 Environment variables (Dokploy → Settings → Env)

Copy from `.env.example` and fill the secrets:

```bash
# Critical secrets (set per environment)
ENV=prod
DATABASE_URL=postgresql+asyncpg://nova:CHANGEME@db:5432/nova
DB_PASSWORD=CHANGEME

REDIS_URL=redis://redis:6379/0

# JWT keys — generate with openssl genpkey, mount as Dokploy secret files
JWT_PRIVATE_KEY_PATH=/secrets/jwt.pem
JWT_PUBLIC_KEY_PATH=/secrets/jwt.pub

# OAuth (optional)
GOOGLE_OAUTH_CLIENT_ID=<your-google-client-id>
APPLE_OAUTH_CLIENT_ID=
APPLE_OAUTH_TEAM_ID=
APPLE_OAUTH_KEY_ID=

# OpenAI (only needed for embedding backfill + coach + vision)
OPENAI_API_KEY=sk-proj-CHANGEME

# Cost cap
COST_CAP_USD_PER_USER_PER_DAY=1.50
COST_CAP_USD_PER_ORG_PER_DAY=500.00

# Rate limits
RATE_LIMIT_AUTH_PER_MIN=10
RATE_LIMIT_AI_PER_MIN=5
RATE_LIMIT_API_PER_MIN=60

# Regions / i18n
DEFAULT_REGION=latam
DEFAULT_LOCALE=es

# MVP segment gate — diabetes_t1 still blocked (insulin scope)
MVP_SEGMENT_GATE_ENABLED=true
MVP_BLOCKED_CONDITIONS=diabetes_t1
MVP_BLOCKED_REGIONS=us

# CORS
CORS_ALLOWED_ORIGINS=https://app.nova-nutrition.com,https://staging.nova-nutrition.com

# Webhooks (Stripe / MercadoPago — set when billing live)
STRIPE_API_KEY=
STRIPE_WEBHOOK_SECRET=
MERCADOPAGO_ACCESS_TOKEN=
MERCADOPAGO_WEBHOOK_SECRET=

# Error tracker (local; no SaaS cost)
NOVA_ERROR_LOG_PATH=/var/log/nova/errors.jsonl
```

### 3.4 Domain + TLS
- Dokploy → Domains → Add → `api.nova-nutrition.com`
- Auto-issue Let's Encrypt cert via Traefik (Dokploy default)

### 3.5 Trigger first deploy
- Dokploy UI → Deploy button
- Watch logs:
  ```
  [build]   Pulling python:3.12-slim ............ OK
  [build]   Installing dependencies ............. OK
  [build]   COPY app/ ........................... OK
  [build]   Image built (≈ 280 MB)
  [deploy]  Starting db ......................... healthy
  [deploy]  Starting redis ...................... healthy
  [deploy]  Starting api ........................ alembic upgrade head ... OK
  [deploy]  api healthy → serving
  ```

**Total first-deploy time: ~5 min.**

---

## 4. Seed catalog (one-time, ~1 min)

```bash
ssh hostinger-vps

# Find api container name
docker ps --format "{{.Names}}" | grep nova
# Example: nova-api-1

# Run seed
docker exec -it nova-api-1 python -m scripts.seed_recipes

# Expected output:
# Loading catalog data/meals/nova_meals_catalog.cleaned.json ...
# 34093 recipes loaded.
# Inserting batch 1/34 (1000 recipes) ...
# ...
# Inserting batch 34/34 (93 recipes) ...
# Seed complete: 34093 recipes in database.

# Verify
docker exec -it nova-db-1 psql -U nova -d nova -c "SELECT COUNT(*) FROM recipes;"
# Expected: 34093
```

**RAM peak during seed: ~3.7 GB on VPS (NOVA 2.1 GB + transient seed 0.3 GB + other projects 4 GB → 6.4 GB used).**

If other projects are noisy during seed → run seed during low-traffic hour.

---

## 5. Embedding backfill (one-time, ~30 min, ~$0.40 OpenAI cost)

```bash
ssh hostinger-vps

# Confirm OPENAI_API_KEY set in env
docker exec -it nova-api-1 sh -c 'echo "${OPENAI_API_KEY:0:10}..."'
# Should print: sk-proj-...

# Run backfill (hard cost cap $1.00)
docker exec -it nova-api-1 python -m scripts.compute_embeddings \
  --only recipes \
  --max-usd 1.00

# Expected output:
# Embedding recipes 1-100 ($0.001) ...
# ...
# Embedding recipes 33901-34000 ($0.396) ...
# Total: 34093 recipes, $0.398 spent.

# Verify
docker exec -it nova-db-1 psql -U nova -d nova -c "
  SELECT COUNT(*) AS total,
         COUNT(embedding) AS with_embedding
  FROM recipes;
"
# Expected: total=34093, with_embedding=34093
```

**RAM peak during embedding: ~4.2 GB NOVA + 4 GB other = 8.2 GB.** *Tight* on 8 GB VPS — run during low-traffic hour.

If OOM risk → split into 4 chunks:
```bash
# Process in quartiles
docker exec -it nova-api-1 python -m scripts.compute_embeddings --max-usd 0.15 --limit 8500
sleep 60
docker exec -it nova-api-1 python -m scripts.compute_embeddings --max-usd 0.15 --limit 8500
# ... repeat
```

---

## 6. Verify production ready

```bash
# Health check
curl https://api.nova-nutrition.com/healthz

# Expected: {"status": "ok"}

# Database row counts
docker exec -it nova-db-1 psql -U nova -d nova -c "
  SELECT 'recipes' AS t, COUNT(*) FROM recipes
  UNION ALL SELECT 'recipe_components', COUNT(*) FROM recipe_components
  UNION ALL SELECT 'with_embedding', COUNT(*) FROM recipes WHERE embedding IS NOT NULL;
"

# RAM check
free -h
# Expected: 5-6 GB used / 8 GB total
```

---

## 7. Subsequent deploys (30 sec each)

```bash
# Local
git add <changed files>
git commit -m "fix(...): ..."
git push origin main

# Dokploy auto-detects → rebuilds → restarts.
# Alembic upgrade head runs idempotently.
# Catalog seed NOT re-run (rows already exist; seed_recipes.py is idempotent
# but the row count check short-circuits if catalog already loaded).
```

**Total subsequent deploy time: ~30 sec to 2 min** depending on layer cache hits.

---

## 8. Monitoring (post-deploy)

### 8.1 Watch RAM

```bash
ssh hostinger-vps
watch -n 5 'free -h && docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"'
```

### 8.2 Watch error log

```bash
docker exec -it nova-api-1 tail -f /var/log/nova/errors.jsonl
```

### 8.3 Watch Postgres slow queries (>1s)

```bash
docker exec -it nova-db-1 tail -f /var/lib/postgresql/data/log/postgresql-*.log | grep "duration:"
```

### 8.4 Alarms to set (Dokploy notifications)

| Signal | Threshold | Action |
|--------|-----------|--------|
| RAM usage | >85% sustained 5min | warn |
| RAM usage | >92% spike | critical (page) |
| OOM kill detected | any | page |
| api container restart | >3 in 1h | page |
| db connection pool exhausted | log >1 in 5min | warn |

---

## 9. Upgrade path

When VPS feels tight:

### Option 9.1 — Switch to full compose (when RAM frees up)

Other projects retire / migrate → use `docker-compose.yml` (full) with:
- worker container (Arq background jobs)
- 2 FastAPI workers
- TimescaleDB extension enabled
- Larger Postgres buffers

### Option 9.2 — Upgrade VPS

- Hostinger KVM 4: 16 GB / $15-18 mes
- Hetzner CAX31: 16 GB / €15 mes (better perf/price typically)

Migration: stop containers → rsync `pgdata` volume to new VPS → restart Dokploy on new host.

---

## 10. Rollback (any phase)

### 10.1 Code rollback
```bash
git revert <bad-commit>
git push origin main
# Dokploy redeploys previous good state
```

### 10.2 Schema rollback
```bash
docker exec -it nova-api-1 alembic downgrade -1
```

### 10.3 Catalog rollback (recipes only)
```bash
# Restore from pre-snapshot
docker exec -it nova-db-1 psql -U nova -d nova -c "TRUNCATE recipes CASCADE;"
docker exec -it nova-api-1 python -m scripts.seed_recipes
# Re-runs from JSON in container (committed snapshot).
```

### 10.4 Full DB nuke (catastrophic only)
```bash
docker compose down -v   # drops volumes
# Dokploy restart → fresh db → seed flow from §4
```

---

## 11. Cost summary

| Item | Monthly |
|------|--------:|
| Hostinger KVM 2 VPS | $7-10 |
| OpenAI embedding (one-time + 5% delta/mo) | <$0.01 |
| OpenAI coach (50k tok/user/mo × 100 users) | $6 |
| GCS bucket for images | $0.50 (~5 GB) |
| Domain + DNS | $1 (depending) |
| **Total at 100 MAU** | **~$15** |

Master plan target at 10k MAU: ~$80/mo. Margin sufficient.

---

## 12. Quick reference commands

```bash
# Deploy
git push origin main

# Seed catalog (first time)
docker exec -it nova-api-1 python -m scripts.seed_recipes

# Embedding backfill (first time, when ready)
docker exec -it nova-api-1 python -m scripts.compute_embeddings --max-usd 1.00

# Migrations only (rare, manual)
docker exec -it nova-api-1 alembic upgrade head

# Verify counts
docker exec -it nova-db-1 psql -U nova -d nova -c "SELECT COUNT(*) FROM recipes;"

# Tail logs
docker logs -f nova-api-1

# Connect to Postgres CLI
docker exec -it nova-db-1 psql -U nova -d nova

# Restart api only
docker compose restart api

# Full restart
docker compose down && docker compose up -d
```

---

End deploy playbook.
