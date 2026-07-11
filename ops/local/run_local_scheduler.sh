#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.local"
PYTHON_BIN="${FQP_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
CHECK_ONLY="${1:-}"

fail() { echo "[fqp-scheduler] ERROR: $*" >&2; exit 1; }

[[ -x "$PYTHON_BIN" ]] || fail "Missing project Python runtime: $PYTHON_BIN"
[[ -f "$ENV_FILE" ]] || fail "Missing $ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

[[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL is not configured"
[[ "$DATABASE_URL" != *"@postgres:"* ]] || fail "Docker hostname is not allowed; use 127.0.0.1"

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11+ is required"
"$PYTHON_BIN" -c 'import psycopg2, os; conn=psycopg2.connect(os.environ["DATABASE_URL"]); conn.close()' \
  || fail "Cannot connect to local PostgreSQL"
"$PYTHON_BIN" -c 'import apscheduler' \
  || fail "APScheduler is not installed in the project Python runtime"

if [[ "$CHECK_ONLY" == "--check" ]]; then
    echo "[fqp-scheduler] local scheduler prerequisites: ok"
    exit 0
fi

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" -m scripts.jobs.run_scheduler
