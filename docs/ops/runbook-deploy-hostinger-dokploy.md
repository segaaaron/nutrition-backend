# Runbook — Deploy NOVA Backend on Hostinger + Dokploy

**Target:** Hostinger KVM 2 (8 GB RAM, 100 GB NVMe, 2 vCPU).
**Stack:** Dokploy → Docker Compose → FastAPI + Postgres-Timescale + Redis + Arq.
**Frontend:** Cloudflare Pages (separate repo).

## 1 — Provision VPS

1. Order Hostinger **VPS KVM 2** in EU region (lowest p95 from LatAm + Europe).
2. SSH in as root, create `nova` user:
   ```bash
   adduser nova && usermod -aG sudo nova && rsync -a ~/.ssh /home/nova/
   chown -R nova:nova /home/nova/.ssh
   ```
3. Harden: disable root SSH, password auth off, ufw allow 22/80/443/tcp.
4. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh && usermod -aG docker nova
   ```

## 2 — Install Dokploy

```bash
curl -sSL https://dokploy.com/install.sh | sh
```

Open `http://<vps-ip>:3000`, create admin account.

## 3 — Cloudflare DNS + SSL

1. Add domain to Cloudflare. Point `api.ms-tech-stack.cloud` A record to VPS IP,
   proxied (orange cloud).
2. SSL/TLS mode: **Full (strict)**.
3. In Dokploy → Settings → Letsencrypt enabled; provide admin email.

## 4 — Repository connection

1. Dokploy → **Create Project** "nova-backend".
2. Source: GitHub → branch `main`.
3. Build: **Docker Compose**; compose file:
   - **MVP / shared VPS:** `docker-compose.mvp.yml` (no worker, ~2.1 GB).
   - **Full / dedicated VPS:** `docker-compose.yml` (worker + larger buffers).
4. Domain: `api.ms-tech-stack.cloud` → container port `8000` (Traefik
   labels in compose already declare host rule + cert resolver `letsencrypt`).
5. Health-check path: `/readyz`.
6. Network: api joins external `dokploy-network` (auto-created by Dokploy
   installer). Verify it exists with `docker network ls | grep dokploy`.
   If absent: re-run Dokploy installer.

## 5 — JWT keypair preparation (owner SSH, one-time)

```bash
sudo mkdir -p /var/dokploy/secrets/nova
cd /var/dokploy/secrets/nova
sudo openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt.pem
sudo openssl rsa -in jwt.pem -pubout -out jwt.pub
sudo chmod 400 jwt.pem
sudo chmod 444 jwt.pub
```

Compose mounts these as `/secrets/jwt.pem` (RO) and `/secrets/jwt.pub` (RO).
The container-side paths match the `JWT_PRIVATE_KEY_PATH` /
`JWT_PUBLIC_KEY_PATH` defaults.

## 6 — Environment variables (Dokploy → Environment)

Compose declares each variable via `${VAR}` substitution (no implicit
`env_file: .env`). Set the following keys in the Dokploy environment panel.
Anything left blank renders the corresponding feature inert.

**Required for boot:**

| Key | Example |
|-----|---------|
| `ENV` | `prod` |
| `LOG_LEVEL` | `INFO` |
| `APP_NAME` | `nova-nutrition-backend` |
| `APP_VERSION` | `0.1.0` |
| `DATABASE_URL` | `postgresql+asyncpg://nova:<DB_PASSWORD>@db:5432/nova` |
| `DB_POOL_SIZE` | `15` |
| `DB_MAX_OVERFLOW` | `10` |
| `DB_POOL_RECYCLE_SECONDS` | `3600` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `JWT_ACCESS_TTL_SECONDS` | `900` |
| `JWT_REFRESH_TTL_SECONDS` | `2592000` |
| `JWT_ISSUER` | `nova-nutrition` |
| `JWT_AUDIENCE` | `nova-mobile` |
| `POSTGRES_USER` | `nova` |
| `POSTGRES_DB` | `nova` |
| `DB_PASSWORD` | (strong random — `openssl rand -hex 24`) |
| `CORS_ALLOWED_ORIGINS` | `https://app.ms-tech-stack.cloud` |
| `SUPPORTED_LOCALES` | `en,es,pt,fr,de` |
| `DEFAULT_LOCALE` | `en` |
| `DEFAULT_REGION` | `mx` |
| `MVP_BLOCKED_CONDITIONS` | `diabetes_t1` |
| `MVP_BLOCKED_REGIONS` | `us` |
| `WEB_MAX_CONCURRENT_REQUESTS` | `200` |
| `RATE_LIMIT_AUTH_PER_MIN` | `10` |
| `RATE_LIMIT_AI_PER_MIN` | `5` |
| `RATE_LIMIT_API_PER_MIN` | `60` |
| `COST_CAP_USD_PER_USER_PER_DAY` | `1.50` |
| `COST_CAP_USD_PER_ORG_PER_DAY` | `500.00` |
| `COST_CAP_ALARM_PCT` | `0.80` |
| `ARQ_JOB_TIMEOUT_SECONDS` | `180` |
| `ARQ_KEEP_RESULT_SECONDS` | `3600` |
| `ARQ_MAX_QUEUE_DEPTH` | `100` |

**AI features:**

| Key | Example |
|-----|---------|
| `OPENAI_API_KEY` | `sk-…` (from 1Password) |
| `OPENAI_VISION_MODEL` | `gpt-4o-2024-08-06` |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-large` |
| `OPENAI_EMBED_DIM` | `1536` |

**OAuth (optional at launch):**

| Key | Notes |
|-----|-------|
| `GOOGLE_OAUTH_CLIENT_ID` | from Google Cloud Console |
| `APPLE_OAUTH_CLIENT_ID` / `APPLE_OAUTH_TEAM_ID` / `APPLE_OAUTH_KEY_ID` | Apple Developer |

**Email (Resend):**

| Key | Notes |
|-----|-------|
| `EMAIL_ENABLED` | `false` until DNS verified, then `true` |
| `RESEND_API_KEY` | `re_…` |

**Billing:**

| Key | Notes |
|-----|-------|
| `STRIPE_API_KEY` | `sk_live_…` |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` |
| `MERCADOPAGO_ACCESS_TOKEN` | `APP_USR-…` (prod) |
| `MERCADOPAGO_WEBHOOK_SECRET` | from MP dashboard |

**Observability (optional):**

| Key | Notes |
|-----|-------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector URL |
| `OTEL_SERVICE_NAME` | `nova-nutrition-backend` |

## 7 — First deploy

1. Click **Deploy** in Dokploy. Watch logs → `nova-api`, `nova-db`, `nova-redis`.
2. Once `nova-db` reports `database system is ready`, exec migrations:
   ```bash
   docker exec -it nova-api alembic upgrade head
   ```
3. Seed catalog (one-off, dev/staging only):
   ```bash
   docker exec -it nova-api python -m scripts.seed_foods
   docker exec -it nova-api python -m scripts.seed_recipes
   docker exec -it nova-api python -m scripts.seed_i18n
   # compute_embeddings DEFERRED — see DOKPLOY_DEPLOY.md §5
   ```

## 8 — Smoke tests post-deploy

```bash
curl -sf https://api.ms-tech-stack.cloud/healthz
curl -sf https://api.ms-tech-stack.cloud/readyz
# Should return 200 with db/redis/arq_queue ok.

# Auth round-trip
curl -X POST https://api.ms-tech-stack.cloud/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@ms-tech-stack.cloud","password":"Test12345!"}'
```

## 9 — Webhook endpoints — register with providers

- Stripe Dashboard → Developers → Webhooks → Add endpoint
  `https://api.ms-tech-stack.cloud/webhooks/stripe`. Events:
  `customer.subscription.created`, `customer.subscription.updated`,
  `customer.subscription.deleted`, `invoice.payment_succeeded`,
  `invoice.payment_failed`.
- Mercado Pago Dashboard → Notifications → Webhooks
  `https://api.ms-tech-stack.cloud/webhooks/mercadopago`.

## 10 — Cron tasks (Dokploy → Cron)

| Cron | Command | Purpose |
|------|---------|---------|
| `0 3 * * *` | `/app/scripts/backup.sh` | Daily backup → R2 |
| `*/15 * * * *` | `docker exec nova-api python -m worker.refresh_aggregates` | Continuous-aggregate refresh nudge |

## 11 — Rollback

1. Dokploy → Deployments → previous build → **Redeploy**.
2. If a migration is involved: `alembic downgrade -1` BEFORE redeploying old code.
3. Restore from latest R2 dump if data corruption — see `runbook-backup-recovery.md`.

## 12 — Verification checklist

- [ ] `/healthz` 200
- [ ] `/readyz` all checks "ok"
- [ ] Grafana dashboard "NOVA core" green
- [ ] Local ErrorTracker capturing events (`GET /admin/errors/recent` returns ring data)
- [ ] First test user can register + log meal + see streak
- [ ] Stripe webhook endpoint test event = 200
