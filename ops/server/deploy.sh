#!/usr/bin/env bash
# Invoke as the checkout owner. Default: plan. Apply needs recorded release evidence.
set -Eeuo pipefail
main() {
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# A first rollout runs this new runner from a staged GitHub archive while
# the live checkout still has the previous code. Select the checkout explicitly.
PROJECT_ROOT="$(cd "${FQP_PROJECT_ROOT:-$SCRIPT_DIR/../..}" && pwd)"
cd "$PROJECT_ROOT"
DEPLOYMENT_INSTANCE="$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)"
write_release_marker() {
    local release_id="$1"
    local marker_dir="$PROJECT_ROOT/.runtime"
    local marker_tmp="$marker_dir/release-id.$$"
    mkdir -p "$marker_dir"
    printf '%s\n' "$release_id" > "$marker_tmp"
    chmod 0644 "$marker_tmp"
    mv -f "$marker_tmp" "$marker_dir/release-id"
}
RELEASE_SHA="${1:-}"
RELEASE_MODE="${2:---plan}"
RELEASE_EVIDENCE="${3:-}"
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Pass the full target commit SHA' >&2; exit 2; }
[[ "$RELEASE_MODE" == '--plan' || "$RELEASE_MODE" == '--apply' ]] || exit 2
[[ -z "$(git status --porcelain)" ]] || { echo 'Checkout must be clean' >&2; exit 1; }
[[ "$(git branch --show-current)" == 'main' ]] || { echo 'Checkout must be on main' >&2; exit 1; }
[[ -x .venv/bin/python ]] || { echo 'Missing application virtualenv' >&2; exit 1; }
git fetch --no-tags origin main
git cat-file -e "$RELEASE_SHA^{commit}"
[[ "$RELEASE_SHA" == "$(git rev-parse origin/main)" ]] || { echo 'Target must equal current origin/main' >&2; exit 1; }
ROLLBACK_SHA="$(git rev-parse HEAD)"
MIGRATION_APPLY_ATTEMPTED=false
FRONTEND_DEV_DEPENDENCIES_CHANGED=false
FRONTEND_PUBLISH_ATTEMPTED=false
WEB_ROOT=/var/www/fqp
has_symlink_component() {
    local path="$1" component="/" part
    local -a parts
    IFS=/ read -r -a parts <<< "$path"
    for part in "${parts[@]}"; do
        [[ -z "$part" ]] && continue
        component="${component%/}/$part"
        [[ ! -L "$component" ]] || return 0
    done
    return 1
}
printf 'Current: %s\nTarget: %s\n' "$ROLLBACK_SHA" "$RELEASE_SHA"
# Runtime dependency changes still require a separately prepared release. Only
# verified Vite/Vitest dev-only updates have a matching rollback path here.
if ! git diff --quiet "$ROLLBACK_SHA" "$RELEASE_SHA" -- requirements.txt requirements-dev.txt pyproject.toml .python-version .node-version apps/model-bridge/package.json apps/model-bridge/package-lock.json; then
    echo 'Dependency/runtime changes require a separately prepared release' >&2
    exit 1
fi
if ! git diff --quiet "$ROLLBACK_SHA" "$RELEASE_SHA" -- apps/frontend/package.json apps/frontend/package-lock.json; then
    if ! .venv/bin/python "$SCRIPT_DIR/release_dependencies.py" "$ROLLBACK_SHA" "$RELEASE_SHA"; then
        echo 'Frontend dependency changes are outside the safe dev-only release policy' >&2
        exit 1
    fi
    FRONTEND_DEV_DEPENDENCIES_CHANGED=true
fi
if [[ "$RELEASE_MODE" == '--plan' ]]; then
    git diff --stat "$ROLLBACK_SHA" "$RELEASE_SHA"
    if [[ "$FRONTEND_DEV_DEPENDENCIES_CHANGED" == true ]]; then
        echo 'Verified frontend Vite/Vitest devDependency update; rollback will reinstall the prior lockfile.'
    fi
    echo 'Plan only. Record quality/rollback/HTTP evidence before --apply; migration copy-dry-run and a recent backup are required only when migrations are pending.'
    exit 0
fi
[[ -f "$RELEASE_EVIDENCE" ]] || { echo 'Missing release evidence JSON' >&2; exit 1; }
.venv/bin/python - "$RELEASE_EVIDENCE" "$RELEASE_SHA" <<'PY'
import json, pathlib, sys
from datetime import UTC, datetime
record = json.loads(pathlib.Path(sys.argv[1]).read_text())
if record.get('target_sha') != sys.argv[2] or any(record.get(key) != 'passed' for key in ('quality', 'rollback_review', 'protected_http_smoke')):
    raise SystemExit('Release evidence must match target SHA with quality, rollback review, and protected HTTP smoke passed')
verified = datetime.fromisoformat(record['verified_at'])
if verified.tzinfo is None or not 0 <= (datetime.now(UTC) - verified).total_seconds() <= 86400:
    raise SystemExit('Release verification evidence must be from the last 24 hours')
PY
sudo -n true
sudo -n -u postgres -- test -x "$PROJECT_ROOT/.venv/bin/python" || {
    echo 'PostgreSQL operating-system user cannot execute the application virtualenv' >&2
    exit 1
}
sudo -n -u postgres -- test -r "$PROJECT_ROOT/ops/server/migrate.py" || {
    echo 'PostgreSQL operating-system user cannot read the migration runner' >&2
    exit 1
}
SERVICES=(fqp-backend fqp-scheduler fqp-worker)
for service in "${SERVICES[@]}"; do sudo -n systemctl is-active --quiet "$service"; done
sudo -n systemctl is-active --quiet nginx
if [[ ! -d "$WEB_ROOT" || ! -w "$WEB_ROOT" ]] || has_symlink_component "$WEB_ROOT"; then
    echo "Nginx web root is unavailable or not writable: $WEB_ROOT" >&2
    exit 1
fi
wait_ready() {
    local attempt
    for attempt in {1..20}; do
        if curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8080/health/ready >/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}
publish_frontend() {
    .venv/bin/python "$SCRIPT_DIR/publish_frontend.py" \
        "$PROJECT_ROOT/apps/frontend/dist" "$WEB_ROOT"
}
rollback() {
    local code=$?
    trap - ERR
    set +e
    echo "Release failed; restoring $ROLLBACK_SHA. Applied additive migrations are retained." >&2
    sudo -n systemctl stop "${SERVICES[@]}"
    if ! git -c core.hooksPath=/dev/null checkout -B main "$ROLLBACK_SHA" \
        || [[ "$(git rev-parse HEAD 2>/dev/null)" != "$ROLLBACK_SHA" ]]; then
        sudo -n systemctl stop "${SERVICES[@]}"
        sudo -n systemctl stop nginx
        echo 'ROLLBACK_REQUIRED: unable to restore the exact prior checkout; application services and nginx remain stopped.' >&2
        exit 1
    fi
    if [[ "$FRONTEND_DEV_DEPENDENCIES_CHANGED" == true ]] && ! npm --prefix apps/frontend ci --ignore-scripts; then
        sudo -n systemctl stop nginx
        echo 'ROLLBACK_REQUIRED: unable to restore frontend dependencies from the prior lockfile; services and nginx remain stopped.' >&2
        exit 1
    fi
    if ! npm --prefix apps/frontend run build; then
        sudo -n systemctl stop nginx
        echo 'ROLLBACK_REQUIRED: prior frontend build failed; services and nginx remain stopped.' >&2
        exit 1
    fi
    if [[ "$FRONTEND_PUBLISH_ATTEMPTED" == true ]] && ! publish_frontend; then
        sudo -n systemctl stop nginx
        echo 'ROLLBACK_REQUIRED: unable to restore prior frontend files; services and nginx remain stopped.' >&2
        exit 1
    fi
    if ! write_release_marker "${ROLLBACK_SHA}-${DEPLOYMENT_INSTANCE}-r"; then
        echo 'ROLLBACK_REQUIRED: unable to write rollback release marker; services remain stopped.' >&2
        sudo -n systemctl stop nginx
        exit 1
    fi
    if [[ "$MIGRATION_APPLY_ATTEMPTED" == true ]]; then
        # The prior code may not fence stale P105 inputs. Fail closed after an
        # apply attempt; an operator must validate the old release before restart.
        sudo -n systemctl stop nginx
        echo 'ROLLBACK_REQUIRED: P105 migration apply was attempted; backend, scheduler, worker and nginx remain stopped.' >&2
        echo 'Do not restart the legacy release until stale recommendations are gated or a compatible release is deployed.' >&2
        exit "${code:-1}"
    fi
    sudo -n systemctl start "${SERVICES[@]}"
    local restored=false attempt
    for attempt in {1..20}; do
        if curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8080/health >/dev/null; then restored=true; break; fi
        sleep 2
    done
    if [[ "$restored" != true ]]; then echo 'ROLLBACK_REQUIRED: old service health did not recover' >&2; fi
    echo 'Inspect service logs and /health before retrying; no destructive SQL rollback was run.' >&2
    exit "${code:-1}"
}
run_migration() {
    .venv/bin/python - "$@" <<'PY'
import subprocess
import sys
from pathlib import Path

from ops.server.migrate import peer_migration_database_url

root = Path.cwd()
# The new trigger must attach to fqp-owned official tables. The migrations
# explicitly transfer their new tables/functions back to the no-login owner.
command = [
    "sudo",
    "-n",
    "-u",
    "postgres",
    "--",
    "env",
    "-u",
    "PGHOST",
    "-u",
    "PGHOSTADDR",
    "-u",
    "PGPORT",
    "-u",
    "PGDATABASE",
    "-u",
    "PGSERVICE",
    "-u",
    "PGSERVICEFILE",
    "-u",
    "PGPASSWORD",
    "-u",
    "PGOPTIONS",
    "DATABASE_URL=" + peer_migration_database_url(),
    str(root / ".venv/bin/python"),
    str(root / "ops/server/migrate.py"),
    *sys.argv[1:],
]
raise SystemExit(subprocess.run(command, check=False).returncode)
PY
}
trap rollback ERR
sudo -n systemctl stop "${SERVICES[@]}"
git -c core.hooksPath=/dev/null checkout -B main "$RELEASE_SHA"
npm --prefix apps/frontend ci --ignore-scripts
npm --prefix apps/frontend run build
MIGRATION_PLAN_OUTPUT="$(run_migration)"
printf '%s\n' "$MIGRATION_PLAN_OUTPUT"
PENDING_MIGRATION_COUNT="$(printf '%s\n' "$MIGRATION_PLAN_OUTPUT" | .venv/bin/python -c '
import ast
import re
import sys

output = sys.stdin.read()
matches = re.findall(r"^Role: [^;]+; pending migrations: (.+)$", output, re.MULTILINE)
if len(matches) != 1:
    raise SystemExit("Could not verify the database migration plan; refusing to continue")
pending = ast.literal_eval(matches[0])
if not isinstance(pending, list) or any(not isinstance(name, str) for name in pending):
    raise SystemExit("Database migration plan has an invalid pending-migration list")
print(len(pending))
')"
if (( PENDING_MIGRATION_COUNT > 0 )); then
    .venv/bin/python - "$RELEASE_EVIDENCE" <<'PY'
import hashlib, json, pathlib, subprocess, sys
from datetime import UTC, datetime
record = json.loads(pathlib.Path(sys.argv[1]).read_text())
if record.get('migration_copy_dry_run') != 'passed':
    raise SystemExit('Pending migrations require a passed migration copy dry-run')
backup_path = record.get('backup_path')
if not isinstance(backup_path, str) or not backup_path:
    raise SystemExit('Pending migrations require a verified pre-deployment backup')
backup = pathlib.Path(backup_path)
try:
    age = datetime.now(UTC).timestamp() - backup.stat().st_mtime
except OSError as exc:
    raise SystemExit('Pending migrations require an accessible pre-deployment backup') from exc
if not 0 <= age <= 3600:
    raise SystemExit('Pending migrations require a pre-deployment backup from the last hour')
with backup.open('rb') as stream:
    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
if checksum != record.get('backup_sha256'):
    raise SystemExit('Backup checksum mismatch')
subprocess.run(['pg_restore', '--list', str(backup)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
    MIGRATION_APPLY_ATTEMPTED=true
    run_migration --apply
else
    echo 'No pending database migrations; migration dry-run and recent-backup gates are not applicable.'
fi
write_release_marker "${RELEASE_SHA}-${DEPLOYMENT_INSTANCE}-d"
sudo -n systemctl start fqp-backend
wait_ready
# Invoke exact protected-route handlers using the application's environment.
# An HTTP authentication smoke still belongs in recorded release evidence.
.venv/bin/python - <<'PY'
import os, shlex
from pathlib import Path
for line in Path('.env.local').read_text().splitlines():
    key, sep, value = line.removeprefix('export ').partition('=')
    if sep and key.strip() in {'DATABASE_URL', 'REDIS_URL'}:
        parts = shlex.split(value, comments=True)
        if len(parts) == 1:
            os.environ[key.strip()] = parts[0]
from apps.backend.src.routers.betting import list_betting_tickets
from scripts.model_performance_cache import get_cached_model_performance_history
page = list_betting_tickets(owner=None, date=None, status=None, limit=1, cursor=None)
if not isinstance(page.get('total'), int):
    raise SystemExit('Ticket ledger smoke failed')
history = get_cached_model_performance_history(window=20, days=365)
if history.get('status') != 'ok':
    raise SystemExit('Model history smoke failed')
print('Ticket/history handler smoke passed')
PY
sudo -n systemctl start fqp-scheduler fqp-worker
for service in "${SERVICES[@]}"; do sudo -n systemctl is-active --quiet "$service"; done
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]]
FRONTEND_PUBLISH_ATTEMPTED=true
publish_frontend
trap - ERR
printf 'Deployed: %s\n' "$RELEASE_SHA"

}
main "$@"
