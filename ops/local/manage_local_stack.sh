#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${FQP_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
POSTGRES_BIN="/opt/homebrew/opt/postgresql@18/bin"
REDIS_BIN="/opt/homebrew/opt/redis/bin"
LABEL="com.fqp.local-stack"
DOMAIN="gui/$(id -u)"
PLIST_FILE="$HOME/Library/LaunchAgents/$LABEL.plist"
FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"
BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"

fail() { echo "[fqp-local-stack] ERROR: $*" >&2; exit 1; }

is_registered() {
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
}

is_healthy() {
    curl --fail --silent --max-time 10 "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null \
        && curl --fail --silent --max-time 5 "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null \
        && "$POSTGRES_BIN/pg_isready" -h 127.0.0.1 -p 5432 -d fqp -U fqp >/dev/null \
        && "$REDIS_BIN/redis-cli" -u redis://127.0.0.1:6379/0 ping 2>/dev/null | grep -q '^PONG$'
}

wait_for_dependencies() {
    local attempt
    for attempt in {1..30}; do
        if "$POSTGRES_BIN/pg_isready" -h 127.0.0.1 -p 5432 -d fqp -U fqp >/dev/null \
            && "$REDIS_BIN/redis-cli" -u redis://127.0.0.1:6379/0 ping 2>/dev/null | grep -q '^PONG$'; then
            return 0
        fi
        sleep 1
    done
    fail "native PostgreSQL/Redis did not become ready"
}

wait_for_health() {
    local attempt
    for attempt in {1..60}; do
        is_healthy && return 0
        sleep 1
    done
    fail "local stack did not become healthy; inspect .runtime/local-stack.launchd.err.log"
}

status() {
    if is_registered && is_healthy; then
        echo "[fqp-local-stack] running frontend=${FRONTEND_PORT} backend=${BACKEND_PORT} postgres=5432 redis=6379"
    elif is_registered; then
        echo "[fqp-local-stack] registered but not healthy"
        return 1
    else
        echo "[fqp-local-stack] stopped"
    fi
}

case "${1:-status}" in
    start)
        command -v brew >/dev/null 2>&1 || fail "Homebrew is not installed"
        [[ -x "$POSTGRES_BIN/pg_isready" ]] || fail "postgresql@18 is not installed"
        [[ -x "$REDIS_BIN/redis-cli" ]] || fail "redis is not installed"
        if launchctl print "$DOMAIN/com.fqp.hybrid" >/dev/null 2>&1 \
            || launchctl print "$DOMAIN/com.fqp.scheduler" >/dev/null 2>&1; then
            fail "a legacy FQP LaunchAgent is still registered"
        fi
        brew services start postgresql@18 >/dev/null
        brew services start redis >/dev/null
        wait_for_dependencies
        "$SCRIPT_DIR/apply_local_migrations.sh"
        "$PYTHON_BIN" -m scripts.local.local_stack_launch_agent --target "$PLIST_FILE" >/dev/null
        if is_registered; then
            launchctl bootout "$DOMAIN/$LABEL"
        fi
        launchctl bootstrap "$DOMAIN" "$PLIST_FILE"
        launchctl kickstart -k "$DOMAIN/$LABEL"
        wait_for_health
        status
        ;;
    stop)
        if is_registered; then
            launchctl bootout "$DOMAIN/$LABEL"
        fi
        rm -f "$PLIST_FILE"
        echo "[fqp-local-stack] stopped"
        ;;
    restart)
        "$0" stop
        "$0" start
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}" >&2
        exit 2
        ;;
esac
