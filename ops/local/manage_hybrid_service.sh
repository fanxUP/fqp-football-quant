#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${FQP_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
LABEL="com.fqp.hybrid"
DOMAIN="gui/$(id -u)"
PLIST_FILE="$HOME/Library/LaunchAgents/$LABEL.plist"
FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"
BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"

fail() { echo "[fqp-hybrid-service] ERROR: $*" >&2; exit 1; }

is_registered() {
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
}

is_healthy() {
    curl --fail --silent --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null \
        && curl --fail --silent --max-time 2 "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null
}

port_is_busy() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_ports_to_stop() {
    local attempt
    for attempt in {1..20}; do
        if ! port_is_busy "$BACKEND_PORT" && ! port_is_busy "$FRONTEND_PORT"; then
            return 0
        fi
        sleep 1
    done
    fail "ports ${FRONTEND_PORT}/${BACKEND_PORT} did not stop"
}

wait_for_health() {
    local attempt
    for attempt in {1..60}; do
        is_healthy && return 0
        sleep 1
    done
    fail "service did not become healthy; inspect $PROJECT_ROOT/.runtime/hybrid.launchd.err.log"
}

status() {
    if is_registered; then
        if is_healthy; then
            echo "[fqp-hybrid-service] running frontend=${FRONTEND_PORT} backend=${BACKEND_PORT}"
        else
            echo "[fqp-hybrid-service] registered but not healthy"
            return 1
        fi
    else
        echo "[fqp-hybrid-service] stopped"
    fi
}

case "${1:-status}" in
    start)
        command -v docker >/dev/null 2>&1 || fail "Docker CLI is not installed"
        docker info >/dev/null 2>&1 || fail "Docker Desktop is not running"
        if launchctl print "$DOMAIN/com.fqp.scheduler" >/dev/null 2>&1; then
            fail "legacy host Scheduler is registered; unregister it before starting hybrid mode"
        fi
        if ! is_registered && { port_is_busy "$BACKEND_PORT" || port_is_busy "$FRONTEND_PORT"; }; then
            fail "ports ${FRONTEND_PORT}/${BACKEND_PORT} are already used by an unmanaged process"
        fi
        "$PYTHON_BIN" -m scripts.local.hybrid_launch_agent --target "$PLIST_FILE" >/dev/null
        if is_registered; then
            launchctl bootout "$DOMAIN/$LABEL"
            wait_for_ports_to_stop
        fi
        launchctl bootstrap "$DOMAIN" "$PLIST_FILE"
        launchctl kickstart -k "$DOMAIN/$LABEL"
        wait_for_health
        status
        ;;
    stop)
        if is_registered; then
            launchctl bootout "$DOMAIN/$LABEL"
            wait_for_ports_to_stop
        fi
        rm -f "$PLIST_FILE"
        echo "[fqp-hybrid-service] stopped"
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
