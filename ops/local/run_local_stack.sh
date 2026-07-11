#!/usr/bin/env bash
set -euo pipefail

# The host checkout is the development source. Docker is rebuilt only after
# the exact revision has been pushed to GitHub.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"

log() { echo "[fqp-docker] $(date '+%H:%M:%S')  $*"; }
fail() { echo "[fqp-docker] ERROR: $*" >&2; exit 1; }
usage() {
    cat <<'EOF'
Usage: ./ops/local/run_local_stack.sh [deploy|status|logs|stop]

deploy (default)  Push a clean local branch to GitHub, rebuild Docker Desktop,
                  and verify the frontend and backend.
status            Show this project's Docker Desktop services.
logs              Follow service logs.
stop              Stop only this project's Docker Desktop services.
EOF
}
require_docker() {
    command -v docker >/dev/null 2>&1 || fail "Docker Desktop CLI is not installed."
    docker info >/dev/null 2>&1 || fail "Docker Desktop is not running."
}

case "${1:-deploy}" in
    deploy)
        require_docker
        git -C "$PROJECT_ROOT" diff --quiet || fail "Working tree has unstaged changes. Commit them before deployment."
        git -C "$PROJECT_ROOT" diff --cached --quiet || fail "Working tree has staged changes. Commit them before deployment."
        [[ -z "$(git -C "$PROJECT_ROOT" ls-files --others --exclude-standard)" ]] || fail "Working tree has untracked files. Add, ignore, or remove them before deployment."
        BRANCH="$(git -C "$PROJECT_ROOT" branch --show-current)"
        [[ -n "$BRANCH" ]] || fail "Detached HEAD cannot be deployed. Check out a branch first."
        REVISION="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
        log "Fetching GitHub state for $BRANCH..."
        git -C "$PROJECT_ROOT" fetch origin "$BRANCH"
        log "Pushing ${REVISION:0:12} to GitHub..."
        git -C "$PROJECT_ROOT" push --set-upstream origin "HEAD:$BRANCH"
        REMOTE_REVISION="$(git -C "$PROJECT_ROOT" ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')"
        [[ "$REMOTE_REVISION" == "$REVISION" ]] || fail "GitHub revision verification failed; Docker deployment was not started."
        export FQP_DEPLOY_REVISION="$REVISION"
        log "Rebuilding Docker Desktop services from ${REVISION:0:12}..."
        docker compose -f "$COMPOSE_FILE" up --detach --build --wait --remove-orphans
        curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null || fail "Backend health check failed after Docker deployment."
        curl --fail --silent --show-error http://127.0.0.1:3000/ >/dev/null || fail "Frontend health check failed after Docker deployment."
        log "Deployment complete: GitHub and Docker Desktop are on ${REVISION:0:12}."
        ;;
    status) require_docker; docker compose -f "$COMPOSE_FILE" ps ;;
    logs) require_docker; exec docker compose -f "$COMPOSE_FILE" logs --follow --tail=100 ;;
    stop) require_docker; docker compose -f "$COMPOSE_FILE" stop ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
esac
