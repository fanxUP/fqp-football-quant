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
