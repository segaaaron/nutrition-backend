#!/usr/bin/env bash
# Nightly pg_dump → R2 backup. Exits non-zero on any failure (cron alerts).
set -euo pipefail

: "${DATABASE_URL:?required}"
: "${RCLONE_REMOTE:=r2:nova-backups}"
: "${SLACK_WEBHOOK_URL:=}"

STAMP="$(date -u +%Y%m%d-%H%M)"
DOW="$(date -u +%u)"  # 1..7 (Mon..Sun)
DOM="$(date -u +%d)"
FILE="/tmp/nova-${STAMP}.dump"

echo "[backup] dump → ${FILE}"
pg_dump -Fc -Z9 --no-owner --no-privileges -d "$DATABASE_URL" -f "$FILE"

# Checksum
sha256sum "$FILE" > "${FILE}.sha256"

# Upload daily
rclone copy "$FILE"          "${RCLONE_REMOTE}/daily/"
rclone copy "${FILE}.sha256" "${RCLONE_REMOTE}/daily/"

# Weekly (Sunday)
if [ "$DOW" = "7" ]; then
    rclone copy "$FILE"          "${RCLONE_REMOTE}/weekly/"
    rclone copy "${FILE}.sha256" "${RCLONE_REMOTE}/weekly/"
fi
# Monthly (1st)
if [ "$DOM" = "01" ]; then
    rclone copy "$FILE"          "${RCLONE_REMOTE}/monthly/"
    rclone copy "${FILE}.sha256" "${RCLONE_REMOTE}/monthly/"
fi

# Prune local
rm -f "$FILE" "${FILE}.sha256"

# Retention — daily > 30d
rclone delete --min-age 30d "${RCLONE_REMOTE}/daily/"

# Notify Slack
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    SIZE=$(rclone size "${RCLONE_REMOTE}/daily/" | tail -1)
    curl -sS -X POST -H 'Content-Type: application/json' \
      -d "{\"text\":\":floppy_disk: nova-backup ok – ${STAMP} – ${SIZE}\"}" \
      "$SLACK_WEBHOOK_URL" >/dev/null || true
fi

echo "[backup] ok – ${STAMP}"
