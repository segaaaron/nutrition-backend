# Runbook — Backup & Disaster Recovery

**Owner:** ops on-call. **Last reviewed:** 2026-05-31.

## Targets

| Metric | MVP value | Notes |
|--------|-----------|-------|
| RPO    | 24 h      | Daily logical dump at 03:00 UTC |
| RTO    | 4 h       | Manual restore to fresh VPS |
| Retention | 30 daily / 4 weekly / 12 monthly | Cloudflare R2 |

## Daily backup (cron)

Runs via Dokploy cron container at 03:00 UTC.

```cron
0 3 * * * /app/scripts/backup.sh >> /var/log/nova-backup.log 2>&1
```

`scripts/backup.sh` performs:
1. `pg_dump -Fc -Z9 -d $DATABASE_URL > /tmp/nova-$(date -u +%Y%m%d).dump`
2. SHA-256 checksum file alongside dump
3. `rclone copy` to `r2:nova-backups/daily/`
4. Verify upload size > 1 MB and checksum matches remote
5. Prune local file
6. Posts success/failure to `#ops` Slack via webhook

Weekly: copies Sunday's dump to `r2:nova-backups/weekly/` (kept 4).
Monthly: copies the 1st-of-month dump to `r2:nova-backups/monthly/` (kept 12).

## Restore test (monthly, first Wednesday)

1. Spin up disposable Hostinger VPS or local docker-compose with the
   `timescale/timescaledb-ha:pg16` image.
2. `rclone copy r2:nova-backups/daily/<latest>.dump /tmp/`
3. Verify SHA against `.sha256` companion file.
4. `pg_restore --create -d postgres /tmp/<latest>.dump`
5. Run smoke queries:
   - `SELECT COUNT(*) FROM users;`
   - `SELECT COUNT(*) FROM food_logs;`
   - `SELECT COUNT(*) FROM achievements;`
6. Boot the API container against the restored DB, hit `/readyz`.
7. Record restore time in `docs/qa/restore-log.md`.

## Disaster recovery (full)

If primary VPS is lost (data corruption, provider outage):

1. **Order replacement VPS** at Hostinger (same KVM 2 spec, EU region).
2. **Bootstrap node** — clone repo, copy `.env.production` from password
   manager, run `docker compose -f docker-compose.yml up -d db redis`.
3. **Restore database** — `rclone copy r2:nova-backups/daily/<latest>.dump .`,
   `docker exec -i nova-db pg_restore -U nova -d nova < <latest>.dump`.
4. **Apply migrations gap** — `docker compose run --rm api alembic upgrade head`.
   (Idempotent: only runs migrations newer than the dump's snapshot.)
5. **Boot app** — `docker compose up -d api worker`.
6. **Re-point DNS** — Cloudflare → new VPS IP, propagation < 60s with TTL=60.
7. **Smoke tests** — auth round-trip, /readyz, log water, list achievements.
8. **Post-mortem** filed within 48 h.

## Cloudflare R2 setup

```bash
rclone config create r2 s3 \
  provider=Cloudflare \
  access_key_id=$R2_KEY \
  secret_access_key=$R2_SECRET \
  endpoint=https://<accountid>.r2.cloudflarestorage.com
```

Store keys in Dokploy secrets, NEVER in repo. Quarterly key rotation.

## Validation checklist

- [ ] Daily cron alert fires if backup didn't run by 03:30 UTC.
- [ ] R2 lifecycle rule deletes daily backups older than 30 days.
- [ ] Restore tested in last 35 days.
- [ ] Slack webhook delivered last 7 success messages.

## Out of scope (post-launch)

- Continuous WAL archiving (RPO < 5 min) — adds Timescale-cloud line item.
- Geo-redundant restore — second VPS in another provider.
