# P119 Acceptance

## A119 — Authentication fix

- Password login succeeds with the restricted Redis runtime ACL (`~session:*`) when a stale session cookie is present.
- Session and release-marker writes use only permitted Redis keys and commands.
- Focused auth tests, Ruff lint and format checks pass; the PR application diff has a passing independent review and required GitHub checks.
- Scope is exactly `apps/backend/src/auth.py` and `tests/test_auth.py`; no dependency or database migration is introduced.

## A119-V4 — Workflow migration

- The pre-migration P118 snapshot is preserved byte-for-byte under `archive/pre-v4-p118-2026-10-21/`, verified by the manifest.
- V4 control files parse as JSON-compatible YAML and use the V4 engine for state transitions, scope, budget, regression and merge checks.
- The original P118 evidence, including its `evidence_update_ci_pending` status, remains archived unchanged; this migration does not assert that P118 completed.
- `python3 -I -S -B .vibe/verify_migration.py` verifies the archive hashes, preserved P118 status, V4 control parsing and pinned engine bundle.
- Independent read-only review has no blocker or major finding.

## Deployment check (post-merge)

Deployment is tracked separately from the merge acceptance: record target revision, rollback revision, migration/dependency readiness, service health and protected-route smoke in the release evidence. A successful password login smoke may be recorded only when private test credentials are available; credentials must not be stored here.

# P120 Acceptance

## A120 — Publish the built frontend safely

- The deploy runner verifies `/var/www/fqp` and every ancestor path component are free of symlinks, and that the root is an existing writable directory, before stopping application services.
- Built assets are validated as regular files and copied atomically; existing hashed assets are retained.
- The local JavaScript and CSS assets referenced by `index.html` are present and byte-identical at the destination before `index.html` is atomically switched.
- External URLs are not mistaken for local files, traversal paths and symlink destinations fail closed, and a failed publish leaves the previous entry page in place.
- Rollback rebuilds and republishes the previous frontend when publication was attempted; restoration failure stops Nginx and reports `ROLLBACK_REQUIRED`.
- Focused isolated filesystem regression tests, shell syntax checks, configured GitHub CI, security review and independent read-only review pass. The V4 merge gate evaluates the committed evidence separately.
- No application API, database schema, runtime dependency or frontend dependency changes are introduced.

## A120-DEPLOY — Production release

Record the exact merged `main` revision, rollback revision, migration/dependency readiness, current service state, deployment runner exit code, release marker, service health, frontend response, readiness checks, protected-route smoke and recent error logs. Apply only after the V4 quality gate passes. If a database migration is pending, satisfy the runner's fresh-backup and copy-dry-run requirements; otherwise record that they are not applicable.
