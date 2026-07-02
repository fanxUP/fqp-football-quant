#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# FQP Local Stack Runner (Codex + Docker Desktop + unpinned dependencies)
#
# Usage:
#   cd ops/local
#   ./run_local_stack.sh              # start all services
#   ./run_local_stack.sh --build-only # only build images
#   ./run_local_stack.sh --down       # stop and remove containers
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --------------- helpers ---------------
log()  { echo "[fqp] $(date '+%H:%M:%S')  $*"; }
fail() { echo "[fqp] ERROR: $*" >&2; exit 1; }

# --------------- check environment ---------------
check_env() {
    log "Checking local environment..."

    # Run the Python environment checker (non-pinning)
    if command -v python3 &>/dev/null; then
        python3 "$PROJECT_ROOT/scripts/local/check_local_environment.py" || true
    elif command -v python &>/dev/null; then
        python "$PROJECT_ROOT/scripts/local/check_local_environment.py" || true
    else
        log "Python not found — skipping environment snapshot"
    fi

    # Ensure data directories exist
    mkdir -p "$PROJECT_ROOT/data/postgres" "$PROJECT_ROOT/data/redis" "$PROJECT_ROOT/backups"

    # Docker preflight
    if ! command -v docker &>/dev/null; then
        fail "Docker is required. Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    fi

    if ! docker info &>/dev/null 2>&1; then
        fail "Docker daemon is not running. Start Docker Desktop first."
    fi

    log "Environment OK."
}

# --------------- start stack ---------------
start_stack() {
    log "Pulling latest base images (unpinned)..."
    docker compose -f "$SCRIPT_DIR/docker-compose.local.yml" pull || true

    log "Building and starting all services..."
    docker compose -f "$SCRIPT_DIR/docker-compose.local.yml" up --build -d

    log ""
    log "============================================"
    log "  FQP Local Stack started"
    log "  Backend:  http://127.0.0.1:8000"
    log "  Frontend: http://127.0.0.1:3000"
    log "  API Docs: http://127.0.0.1:8000/docs"
    log "  Health:   http://127.0.0.1:8000/health"
    log "============================================"
    log ""
    log "Services running:"
    docker compose -f "$SCRIPT_DIR/docker-compose.local.yml" ps
}

build_only() {
    log "Building images without starting..."
    docker compose -f "$SCRIPT_DIR/docker-compose.local.yml" build
    log "Build complete."
}

stop_stack() {
    log "Stopping and removing containers..."
    docker compose -f "$SCRIPT_DIR/docker-compose.local.yml" down
    log "Stack stopped."
}

# --------------- main ---------------
check_env

case "${1:-}" in
    --build-only)
        build_only
        ;;
    --down)
        stop_stack
        ;;
    *)
        start_stack
        ;;
esac
