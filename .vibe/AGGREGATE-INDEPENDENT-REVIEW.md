# Independent review: P107/P138 aggregate candidate

Review completed 2026-11-03 (Beijing time) against the accumulated candidate based on `main` at `4a7a37aa57b885cc3ae332731b6a6e273dd49bff`.

## Outcome

The read-only review found **no blocker, major, or new minor code findings** across the 52 counted paths. The 51 owned P107/P138 paths are suitable for exact-head CI. The unowned `uv.lock` must be excluded from staging.

The review covered the P107-06G rollback atomicity and invalidation tests, P107-06C cutoff/order/label behavior, recursive selector contexts, feature-batch API/types/rendering, prediction group and feature-context identity, summary response compatibility, and migration behavior. It confirmed that P104 values have not been shown to affect ordinary-model probabilities and that production grants, migration-copy rehearsal, and natural runtime behavior remain unverified.

The reviewer made no edits, ran no tests, and did not access production. This review does not replace exact-head GitHub CI, the production schema/data-copy migration rehearsal, release preflight, or post-deployment observation. The only change after review was two malformed-snapshot regression cases in an already-reviewed test file; no product behavior changed.

## Follow-up review — 2026-11-04 00:50 Beijing time

A second read-only review checked the final candidate after exact-head CI exposed stale API mocks, a stale explanation-artifact assertion, and a repeated-read performance issue. The approved scope now contains **54 owned paths**: the original 51 plus three regression files (`tests/test_api/test_api_versioning.py`, `tests/test_api/test_prediction_research.py`, and `tests/test_computation/test_prediction_semantics.py`). The two query scripts are already among the original 51. `uv.lock` remains listed only as an excluded path, is not approved, and is unchanged.

The reviewer confirmed that the scope and 54-file budget agree, the current local evidence is fresh, and no product-code finding remains. The latest V4 local-candidate validation completed at 00:48 with exit code 0 on revision `c89987e5d07528fed1dda1a80e0ef2532bf852c2` and business-tree fingerprint `9306bc66a06bb9dbfaa66b1a6e95e6d7c0b37f91c96acd5666e062e772a141e6`. It covered the current PostgreSQL/Python regressions, whole-repository Ruff/format/Mypy/compileall, frontend tests/typecheck/build, scope, budget, and diff checks. This is a review of recorded evidence; the reviewer did not rerun tests.

This follow-up supersedes the earlier 52-path count and the earlier statement that only two snapshot tests changed after review. The candidate is suitable to commit and push for exact-head CI. Production-copy rehearsal, release preflight, deployment, and post-deployment observation remain open.
