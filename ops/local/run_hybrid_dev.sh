#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"
HYBRID_FILE="$SCRIPT_DIR/docker-compose.hybrid.yml"
DOCKER_ENV_FILE="$SCRIPT_DIR/.env.local"
POSTGRES_PORT="${FQP_POSTGRES_PORT:-5433}"
REDIS_PORT="${FQP_REDIS_PORT:-6379}"

log() { echo "[fqp-hybrid] $(date '+%H:%M:%S')  $*"; }
fail() { echo "[fqp-hybrid] ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker Desktop CLI is not installed."
docker info >/dev/null 2>&1 || fail "Docker Desktop is not running."
[[ -f "$DOCKER_ENV_FILE" ]] || fail "Missing $DOCKER_ENV_FILE."

set -a
# shellcheck disable=SC1090
source "$DOCKER_ENV_FILE"
set +a

[[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL is missing in $DOCKER_ENV_FILE."
[[ "$DATABASE_URL" == *"@postgres:5432"* ]] \
    || fail "Docker DATABASE_URL must target postgres:5432."

HOST_DATABASE_URL="${DATABASE_URL/@postgres:5432/@127.0.0.1:${POSTGRES_PORT}}"
HOST_REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
HOST_REDIS_URL="${HOST_REDIS_URL/redis:6379/127.0.0.1:${REDIS_PORT}}"

COMPOSE=(docker compose -f "$COMPOSE_FILE" -f "$HYBRID_FILE")

log "Stopping only the Docker frontend/backend to release ports 8066/8006..."
docker compose -f "$COMPOSE_FILE" stop frontend backend >/dev/null

log "Keeping PostgreSQL, Redis, Worker, Scheduler and Grafana in Docker..."
"${COMPOSE[@]}" up --detach --no-build postgres redis worker scheduler grafana

log "Starting host frontend/backend against Docker PostgreSQL on port ${POSTGRES_PORT}..."
cd "$PROJECT_ROOT"
exec env \
    FQP_DATABASE_URL_OVERRIDE="$HOST_DATABASE_URL" \
    FQP_REDIS_URL_OVERRIDE="$HOST_REDIS_URL" \
    "$SCRIPT_DIR/run_local_dev.sh"
