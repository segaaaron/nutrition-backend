#!/bin/bash
# NOVA Nutrition — API container entrypoint
#
# Runs Alembic migrations BEFORE starting the FastAPI app. Idempotent.
# Safe under multi-instance boot: Alembic uses a version table lock.
#
# Behavior:
#   - On boot: applies any pending migrations (alembic upgrade head)
#   - Logs migration output to stdout (visible in Dokploy logs)
#   - If migration fails: exits non-zero so container marks as unhealthy
#   - On success: hands off to uvicorn
#
# Override via env var SKIP_MIGRATIONS=1 (NOT recommended in prod).

set -euo pipefail

log() {
    echo "[entrypoint] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

if [[ "${SKIP_MIGRATIONS:-0}" == "1" ]]; then
    log "WARN: SKIP_MIGRATIONS=1, skipping alembic upgrade head"
else
    log "Running alembic upgrade head..."
    if python -m alembic upgrade head; then
        log "Migrations applied successfully"
    else
        log "ERROR: alembic upgrade head failed, aborting boot"
        exit 1
    fi

    log "Current DB revision:"
    python -m alembic current || log "WARN: could not read current revision"

    # Phase 4 i18n — seed error/validation translations. Idempotent UPSERT,
    # safe on every boot. Override with SKIP_I18N_ERROR_SEED=1.
    if [[ "${SKIP_I18N_ERROR_SEED:-0}" == "1" ]]; then
        log "WARN: SKIP_I18N_ERROR_SEED=1, skipping i18n error seed"
    else
        log "Seeding i18n error translations..."
        if python -m scripts.seed_i18n_errors; then
            log "i18n error translations seeded"
        else
            log "WARN: seed_i18n_errors failed (non-fatal, errors will fall back to EN)"
        fi
    fi
fi

# Sprint 3 D3 — catalogue boot guard.
# Refuses to start the API if any R6 fail-closed critical column is
# above the hard NULL threshold (default 10%). Without this guard a
# broken catalogue ingest would boot a production API that silently
# filters every recipe for affected medical-condition users.
# Override with SKIP_CATALOG_BOOT_GUARD=1 (NOT recommended in prod).
if [[ "${SKIP_CATALOG_BOOT_GUARD:-0}" == "1" ]]; then
    log "WARN: SKIP_CATALOG_BOOT_GUARD=1, skipping catalogue completeness check"
else
    log "Running catalogue completeness boot guard (hard threshold)..."
    if python -m scripts.catalog_completeness_audit --boot-guard --json; then
        log "Catalogue boot guard passed"
    else
        rc=$?
        if [[ $rc -eq 3 ]]; then
            log "FATAL: catalogue NULL ratio above hard threshold (rc=3). Refusing to boot."
            log "Inspect output above, run 'make catalog-audit' locally, backfill, and redeploy."
            exit 1
        else
            log "WARN: catalogue boot guard returned rc=$rc (non-fatal, not exit-3). Continuing."
        fi
    fi
fi

log "Starting uvicorn..."
exec "$@"
