# Acceptance: P107 aggregate candidate release readiness

- Scope/budget remain exactly 52 counted paths, 51 owned paths, 5 new files, 2 migration files, 0 dependency additions; `uv.lock` is excluded from staging.
- Current candidate regressions, migration tests on disposable PostgreSQL 16, API tests, frontend tests/typecheck/build, Ruff, Mypy and diff checks pass.
- Independent full-candidate review, security review and migration review are PASS.
- GitHub CI passes for the exact `main` commit.
- Migration 131 passes a current production schema/data-copy rehearsal with preserved source rows, expected grants, bounded locks and an executable recovery plan.
- Production migration/deployment passes health, critical-path, logs/metrics and natural-run verification. A107 remains incomplete until consumer behavior and resource outcomes are observed.
