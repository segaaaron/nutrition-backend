#!/usr/bin/env bash
# Emergency restore from R2. Validates SHA, restores into a fresh database.
#
# Usage:
#   DATABASE_URL=postgresql://... ./scripts/restore.sh latest
#   DATABASE_URL=postgresql://... ./scripts/restore.sh nova-20260530-0300.dump
set -euo pipefail

: "${DATABASE_URL:?required}"
: "${RCLONE_REMOTE:=r2:nova-backups}"

WHICH="${1:-latest}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ "$WHICH" = "latest" ]; then
    FILE=$(rclone lsf "${RCLONE_REMOTE}/daily/" --include "*.dump" \
              | sort | tail -1)
else
    FILE="$WHICH"
fi

echo "[restore] downloading ${FILE}"
rclone copy "${RCLONE_REMOTE}/daily/${FILE}"          "$TMP/"
rclone copy "${RCLONE_REMOTE}/daily/${FILE}.sha256"   "$TMP/"

cd "$TMP"
echo "[restore] verifying checksum"
sha256sum -c "${FILE}.sha256"

echo "[restore] pg_restore into target database"
pg_restore --clean --if-exists --no-owner --no-privileges \
           -d "$DATABASE_URL" "${FILE}"

echo "[restore] applying alembic upgrade head"
cd - >/dev/null
alembic upgrade head

echo "[restore] DONE — verify with:"
echo "  psql \$DATABASE_URL -c 'SELECT COUNT(*) FROM users;'"
