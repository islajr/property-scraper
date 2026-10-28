#!/usr/bin/env bash
# Lightweight scheduled entry point: uses the existing venv and Python .env loader.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

MODE_ARGS=()
case "${RENTAL_RECOVERY_MODE:-preview}" in
    preview) ;;
    apply) MODE_ARGS+=(--apply) ;;
    *) echo 'RENTAL_RECOVERY_MODE must be preview or apply' >&2; exit 2 ;;
esac

export PYTHONUNBUFFERED=1
exec "$PROJECT_DIR/.venv/bin/python" scripts/backfill_rental_pricing.py run \
    "${MODE_ARGS[@]}" \
    --state-dir "${RENTAL_RECOVERY_STATE:-$HOME/.local/state/property-scraper/rental-recovery}" \
    --max-listings "${RENTAL_RECOVERY_MAX_LISTINGS:-300}" \
    --max-http-requests "${RENTAL_RECOVERY_MAX_HTTP_REQUESTS:-1000}" \
    --max-seconds "${RENTAL_RECOVERY_MAX_SECONDS:-1800}"
