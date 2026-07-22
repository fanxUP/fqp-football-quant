#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/apps/frontend"
ENV_FILE="$PROJECT_ROOT/.env.local"
FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"
BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"

log() { echo "[fqp-dev] $(date '+%H:%M:%S')  $*"; }
fail() { echo "[fqp-dev] ERROR: $*" >&2; exit 1; }

command -v node >/dev/null 2>&1 || fail "Node.js is required."
command -v npm >/dev/null 2>&1 || fail "npm is required."

PYTHON_BIN="${FQP_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    if command -v python3.14 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3.14)"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    else
        fail "Python 3.14 is required."
    fi
fi
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' \
    || fail "Python 3.14 is required; current runtime is $PYTHON_BIN ($PYTHON_VERSION)."

if [[ ! -f "$ENV_FILE" ]]; then
    fail "Missing $ENV_FILE. Copy .env.local.example to .env.local and configure the Docker database port."
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Hybrid development keeps PostgreSQL/Redis in Docker while running the UI and
# API on macOS. Explicit overrides prevent .env.local from silently selecting a
# different host database.
DATABASE_URL="${FQP_DATABASE_URL_OVERRIDE:-${DATABASE_URL:-}}"
REDIS_URL="${FQP_REDIS_URL_OVERRIDE:-${REDIS_URL:-}}"
export DATABASE_URL REDIS_URL

[[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL is not configured in .env.local."
if [[ "$DATABASE_URL" == *"@postgres:"* ]]; then
    fail "DATABASE_URL still uses Docker hostname 'postgres'. Use 127.0.0.1 for local development."
fi

"$PYTHON_BIN" -c 'import psycopg2, os; conn=psycopg2.connect(os.environ["DATABASE_URL"]); conn.close()' \
    || fail "Cannot connect to the Docker PostgreSQL database configured by DATABASE_URL."

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    log "Installing frontend dependencies..."
    npm --prefix "$FRONTEND_DIR" install
fi

cleanup() {
    log "Stopping local development processes..."
    [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

log "Starting backend at http://127.0.0.1:${BACKEND_PORT}"
cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

log "Starting frontend at http://127.0.0.1:${FRONTEND_PORT}"
VITE_PROXY_TARGET="${VITE_PROXY_TARGET:-http://127.0.0.1:${BACKEND_PORT}}" \
    npm --prefix "$FRONTEND_DIR" run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

wait "$BACKEND_PID"
