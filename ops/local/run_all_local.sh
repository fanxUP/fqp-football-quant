#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.local"
PYTHON_BIN="${FQP_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
POSTGRES_BIN="${FQP_POSTGRES_BIN:-/opt/homebrew/opt/postgresql@18/bin}"
REDIS_BIN="${FQP_REDIS_BIN:-/opt/homebrew/opt/redis/bin}"

fail() { echo "[fqp-local-stack] ERROR: $*" >&2; exit 1; }

[[ -x "$PYTHON_BIN" ]] || fail "missing Python runtime: $PYTHON_BIN"
[[ -f "$ENV_FILE" ]] || fail "missing $ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

[[ "${DATABASE_URL:-}" == *"@127.0.0.1:5432/fqp" ]] \
    || fail "DATABASE_URL must use the native PostgreSQL database on 127.0.0.1:5432/fqp"
[[ "${REDIS_URL:-}" == "redis://127.0.0.1:6379/0" ]] \
    || fail "REDIS_URL must use the native Redis service on 127.0.0.1:6379/0"

"$POSTGRES_BIN/pg_isready" -h 127.0.0.1 -p 5432 -d fqp -U fqp >/dev/null \
    || fail "native PostgreSQL is not ready"
"$REDIS_BIN/redis-cli" -u "$REDIS_URL" ping | grep -q '^PONG$' \
    || fail "native Redis is not ready"

export FQP_PYTHON_BIN="$PYTHON_BIN"
export FQP_SCHEDULER_HEARTBEAT_MODE=local
export FQP_ODDS_DISPATCH_OWNER=worker
cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" -u -m scripts.local.local_process_supervisor
