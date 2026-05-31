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

1. Add domain to Cloudflare. Point `api.nova-nutrition.com` A record to VPS IP,
   proxied (orange cloud).
2. SSL/TLS mode: **Full (strict)**.
3. In Dokploy → Settings → Letsencrypt enabled; provide admin email.

## 4 — Repository connection

1. Dokploy → **Create Project** "nova-backend".
2. Source: GitHub → branch `main`.
3. Build: Docker Compose; compose file: `docker-compose.yml`.
4. Health-check path: `/readyz`.

## 5 — Environment variables (Dokploy → Secrets)

| Key | Example | Notes |
|-----|---------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://nova:****@db:5432/nova` | strong pwd |
| `REDIS_URL` | `redis://redis:6379/0` | |
| `JWT_PRIVATE_KEY_PATH` | `/secrets/jwt.pem` | mounted |
| `JWT_PUBLIC_KEY_PATH` | `/secrets/jwt.pub` | mounted |
| `OPENAI_API_KEY` | `sk-…` | from 1Password |
| `STRIPE_API_KEY` | `sk_live_…` | live key |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` | Stripe dashboard |
| `MERCADOPAGO_ACCESS_TOKEN` | `APP_USR-…` | prod token |
| `GOOGLE_OAUTH_CLIENT_ID` | `…apps.googleusercontent.com` | |
| `APPLE_OAUTH_*` | (set 3 vars) | |
| `SENTRY_DSN` | `https://…@sentry.io/…` | |
| `R2_KEY` / `R2_SECRET` | (R2 backup creds) | used by backup cron |
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/…` | ops alerts |
| `CORS_ALLOWED_ORIGINS` | `https://app.nova-nutrition.com` | |

JWT keypair: generate locally `openssl genpkey -algorithm RSA -out jwt.pem`,
mount via Dokploy "Mounts" feature into `/secrets/`.

## 6 — First deploy

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
   docker exec -it nova-api python -m scripts.compute_embeddings
   ```

## 7 — Smoke tests post-deploy

```bash
curl -sf https://api.nova-nutrition.com/healthz
curl -sf https://api.nova-nutrition.com/readyz
# Should return 200 with db/redis/arq_queue ok.

# Auth round-trip
curl -X POST https://api.nova-nutrition.com/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@nova-nutrition.com","password":"Test12345!"}'
```

## 8 — Webhook endpoints — register with providers

- Stripe Dashboard → Developers → Webhooks → Add endpoint
  `https://api.nova-nutrition.com/webhooks/stripe`. Events:
  `customer.subscription.created`, `customer.subscription.updated`,
  `customer.subscription.deleted`, `invoice.payment_succeeded`,
  `invoice.payment_failed`.
- Mercado Pago Dashboard → Notifications → Webhooks
  `https://api.nova-nutrition.com/webhooks/mercadopago`.

## 9 — Cron tasks (Dokploy → Cron)

| Cron | Command | Purpose |
|------|---------|---------|
| `0 3 * * *` | `/app/scripts/backup.sh` | Daily backup → R2 |
| `*/15 * * * *` | `docker exec nova-api python -m worker.refresh_aggregates` | Continuous-aggregate refresh nudge |

## 10 — Rollback

1. Dokploy → Deployments → previous build → **Redeploy**.
2. If a migration is involved: `alembic downgrade -1` BEFORE redeploying old code.
3. Restore from latest R2 dump if data corruption — see `runbook-backup-recovery.md`.

## 11 — Verification checklist

- [ ] `/healthz` 200
- [ ] `/readyz` all checks "ok"
- [ ] Grafana dashboard "NOVA core" green
- [ ] Sentry receiving events from API
- [ ] First test user can register + log meal + see streak
- [ ] Stripe webhook endpoint test event = 200
