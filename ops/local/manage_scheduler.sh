#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
PID_FILE="$RUNTIME_DIR/scheduler.pid"
LOG_FILE="$RUNTIME_DIR/scheduler.log"
LAUNCHER="$SCRIPT_DIR/run_local_scheduler.sh"
PYTHON_BIN="${FQP_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
LABEL="com.fqp.scheduler"
DOMAIN="gui/$(id -u)"
PLIST_FILE="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$RUNTIME_DIR"

fail() {
  echo "[fqp-scheduler] ERROR: $*" >&2
  exit 1
}

ensure_launchd_access() {
  case "$PROJECT_ROOT" in
    *"/Library/Mobile Documents/"*)
      fail "launchd cannot access this iCloud Drive checkout. Move the project to a non-iCloud path before using managed scheduler start; otherwise run ./ops/local/run_local_scheduler.sh in an interactive terminal."
      ;;
  esac
}

is_registered() {
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
}

is_running() {
  is_registered || return 1
  "$PYTHON_BIN" -c 'from scripts.local.scheduler_heartbeat import is_scheduler_alive; raise SystemExit(0 if is_scheduler_alive() else 1)'
}

status() {
  if is_running; then
    local pid=""
    [[ -f "$PID_FILE" ]] && pid="$(cat "$PID_FILE")"
    echo "[fqp-scheduler] running${pid:+ pid=$pid}"
  else
    if is_registered; then
      echo "[fqp-scheduler] launchd registered but scheduler heartbeat is offline"
    else
      echo "[fqp-scheduler] stopped"
    fi
    [[ -f "$PID_FILE" ]] && rm -f "$PID_FILE"
  fi
}

case "${1:-status}" in
  start)
    if is_running; then
      echo "[fqp-scheduler] already running"
      exit 0
    fi
    ensure_launchd_access
    "$LAUNCHER" --check >/dev/null
    "$PYTHON_BIN" -m scripts.local.scheduler_launch_agent --target "$PLIST_FILE" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$DOMAIN" "$PLIST_FILE"
    launchctl kickstart -k "$DOMAIN/$LABEL"
    sleep 1
    is_running || fail "launchd registered the service but no scheduler heartbeat was created; inspect $RUNTIME_DIR/scheduler.launchd.err.log"
    status
    ;;
  stop)
    if is_running; then
      launchctl bootout "$DOMAIN/$LABEL"
      rm -f "$PID_FILE"
      echo "[fqp-scheduler] stopped"
    else
      rm -f "$PID_FILE"
      echo "[fqp-scheduler] already stopped"
    fi
    ;;
  status)
    status
    ;;
  *)
    echo "Usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
