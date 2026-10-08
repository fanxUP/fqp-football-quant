#!/usr/bin/env bash
# Invoke as the checkout owner. Default: plan. Apply needs recorded release evidence.
set -Eeuo pipefail
main() {
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# A first rollout runs this new runner from a staged GitHub archive while
# the live checkout still has the previous code. Select the checkout explicitly.
PROJECT_ROOT="$(cd "${FQP_PROJECT_ROOT:-$SCRIPT_DIR/../..}" && pwd)"
cd "$PROJECT_ROOT"
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
printf 'Current: %s\nTarget: %s\n' "$ROLLBACK_SHA" "$RELEASE_SHA"
# This release runner handles code/schema changes; runtime or dependency changes
# require their own prepared rollout so a code rollback is sufficient here.
if ! git diff --quiet "$ROLLBACK_SHA" "$RELEASE_SHA" -- requirements.txt requirements-dev.txt pyproject.toml .python-version .node-version apps/frontend/package.json apps/frontend/package-lock.json; then
    echo 'Dependency/runtime changes require a separately prepared release' >&2
    exit 1
fi
if [[ "$RELEASE_MODE" == '--plan' ]]; then
    git diff --stat "$ROLLBACK_SHA" "$RELEASE_SHA"
    echo 'Plan only. Review target SQL and record copy dry-run/quality/backup evidence before --apply.'
    exit 0
fi
[[ -f "$RELEASE_EVIDENCE" ]] || { echo 'Missing release evidence JSON' >&2; exit 1; }
.venv/bin/python - "$RELEASE_EVIDENCE" "$RELEASE_SHA" <<'PY'
import hashlib, json, pathlib, subprocess, sys
from datetime import UTC, datetime
record = json.loads(pathlib.Path(sys.argv[1]).read_text())
if record.get('target_sha') != sys.argv[2] or any(record.get(key) != 'passed' for key in ('quality', 'migration_copy_dry_run', 'rollback_review', 'protected_http_smoke')):
    raise SystemExit('Release evidence must match target SHA with all required checks passed')
verified = datetime.fromisoformat(record['verified_at'])
if verified.tzinfo is None or not 0 <= (datetime.now(UTC) - verified).total_seconds() <= 86400:
    raise SystemExit('Release verification evidence must be from the last 24 hours')
backup = pathlib.Path(record['backup_path'])
if not 0 <= datetime.now(UTC).timestamp() - backup.stat().st_mtime <= 3600:
    raise SystemExit('Pre-deployment backup must be from the last hour')
with backup.open('rb') as stream:
    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
if checksum != record.get('backup_sha256'):
    raise SystemExit('Backup checksum mismatch')
subprocess.run(['pg_restore', '--list', str(backup)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
sudo -n true
SERVICES=(fqp-backend fqp-scheduler fqp-worker)
for service in "${SERVICES[@]}"; do sudo -n systemctl is-active --quiet "$service"; done
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
rollback() {
    local code=$?
    trap - ERR
    set +e
    echo "Release failed; restoring $ROLLBACK_SHA. Applied additive migrations are retained." >&2
    sudo -n systemctl stop "${SERVICES[@]}"
    git -c core.hooksPath=/dev/null checkout -B main "$ROLLBACK_SHA"
    npm --prefix apps/frontend run build
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
trap rollback ERR
sudo -n systemctl stop "${SERVICES[@]}"
git -c core.hooksPath=/dev/null checkout -B main "$RELEASE_SHA"
npm --prefix apps/frontend ci --ignore-scripts
npm --prefix apps/frontend run build
.venv/bin/python ops/server/migrate.py
.venv/bin/python ops/server/migrate.py --apply
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
trap - ERR
printf 'Deployed: %s\n' "$RELEASE_SHA"

}
main "$@"
