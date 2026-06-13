#!/usr/bin/env bash
# =============================================================================
# run.sh — PS-0 PropertyScraper local run script
#
# Usage:
#   ./run.sh                  — weekly discovery run (scrape all portals)
#   ./run.sh --health-check   — bi-weekly health check (verify listing URLs)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
LOG_FILE="$SCRIPT_DIR/scraper.log"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[run]${NC} $*"; }
warn()  { echo -e "${YELLOW}[run]${NC} $*"; }
error() { echo -e "${RED}[run]${NC} $*" >&2; }

# ── Detect run mode ────────────────────────────────────────────────────────────
MODE_FLAG=""
for arg in "$@"; do
    [[ "$arg" == "--health-check" ]] && MODE_FLAG="--health-check" && break
done

# ── 1. Initialise pyenv so its shims are on PATH ───────────────────────────────
export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
if [[ -d "$PYENV_ROOT/bin" ]]; then
    export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
    eval "$(pyenv init -)" 2>/dev/null || true
    info "pyenv initialised: $(pyenv version 2>/dev/null || echo 'unknown')"
else
    warn "pyenv not found at $PYENV_ROOT — using system Python"
fi

# ── 2. Check .env ─────────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    error ".env not found. Copy .env.example → .env and fill in credentials."
    exit 1
fi
set -a; source .env; set +a
[[ -z "${DATABASE_URL:-}" ]] && { error "DATABASE_URL not set in .env"; exit 1; }
info "Credentials loaded."

# ── 3. Pick Python interpreter (prefer 3.12) ──────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done

[[ -z "$PYTHON" ]] && { error "No Python 3 interpreter found."; exit 1; }

PY_VERSION=$("$PYTHON" --version 2>&1)
info "Using: $PY_VERSION ($PYTHON)"

if "$PYTHON" -c "import sys; sys.exit(1 if sys.version_info >= (3,13) else 0)" 2>/dev/null; then
    : # 3.12 or below — all wheels are stable
else
    warn "Python 3.13 detected. Some wheels may compile from source (slower first run)."
    warn "For a smoother experience: pyenv install 3.12.9 && pyenv local 3.12.9"
    warn "Then: rm -rf .venv && ./run.sh"
fi

# ── 4. Virtualenv ─────────────────────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    VENV_PY=$("$VENV_DIR/bin/python3" --version 2>&1 || echo "unknown")
    if [[ "$VENV_PY" != "$PY_VERSION" ]]; then
        warn "Venv Python ($VENV_PY) differs from selected ($PY_VERSION). Rebuilding..."
        rm -rf "$VENV_DIR"
    fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtualenv at .venv/ ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
info "Virtualenv active: $(python3 --version)"

# ── 5. Dependencies ───────────────────────────────────────────────────────────
info "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ── 6. Playwright browser ─────────────────────────────────────────────────────
# Only needed for discovery mode (Jiji parser), but keeping it here keeps
# both modes consistent and the install is a no-op when already cached.
info "Ensuring Playwright Chromium is installed (cached after first run)..."
playwright install chromium 2>&1 | grep -E "(Downloading|chromium|already|Browser)" || true

# ── 7. Apply DB schema (idempotent — safe to run on every invocation) ─────────
info "Applying DB schema migrations to Supabase..."
python3 - <<'PYEOF'
import psycopg2, os, pathlib

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True

schema_dir = pathlib.Path("schema")
migrations  = sorted(schema_dir.glob("*.sql"))

with conn.cursor() as cur:
    for migration in migrations:
        print(f"  applying {migration.name} ...", end=" ")
        cur.execute(migration.read_text())
        print("OK")

conn.close()
PYEOF

# ── 8. Run scraper ────────────────────────────────────────────────────────────
echo ""
if [[ -n "$MODE_FLAG" ]]; then
    info "Mode: HEALTH CHECK — $(date -u '+%Y-%m-%d %H:%M UTC')"
else
    info "Mode: DISCOVERY — $(date -u '+%Y-%m-%d %H:%M UTC')"
fi
info "Log: $LOG_FILE"
echo ""

START_TS=$(date +%s)
set +e
python3 -m scraper.orchestrator "$@"
SCRAPER_EXIT=$?
set -e
DURATION=$(( $(date +%s) - START_TS ))

echo ""
if [[ $SCRAPER_EXIT -eq 0 ]]; then
    info "Done in $(( DURATION/60 ))m $(( DURATION%60 ))s — check Telegram for summary."
else
    error "Scraper exited with code $SCRAPER_EXIT after $(( DURATION/60 ))m $(( DURATION%60 ))s."
    echo "── last 30 lines of log ──────────────────────────────────────────────"
    tail -30 "$LOG_FILE" 2>/dev/null || echo "(no log file)"
    echo "──────────────────────────────────────────────────────────────────────"
fi

exit $SCRAPER_EXIT