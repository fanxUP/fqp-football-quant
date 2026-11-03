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

## Release-gate follow-up review — 2026-11-04

The reviewer rechecked the migration-131 no-backup gate after it was extended to require a production-host signature. **PASS: no remaining signature bypass or fail-open path was found.** The detached signature covers the complete report bytes; the verifier checks the signed report hash, target SHA, pending migration set, pinned up/down SQL hashes, current production-copy timestamp, copied source tables, bounded match samples, queue seed, runtime-role permissions, trigger/refresh evidence, and rollback proof. Missing, unsigned, tampered, stale, or mismatched evidence is rejected. Verification and signing now use `/usr/bin/ssh-keygen`; a regression confirms a PATH-injected executable is ignored.

The reviewer clarified the evidence boundary: the host signature proves that a holder of the production host key endorsed the report; it does not independently prove the reported database facts. The migration gate therefore remains closed until an actual current targeted copy rehearsal is completed and its report is signed. The previous full-copy attempt was interrupted when production storage I/O rose sharply; it produced no report and must not be represented as a pass.

The final local candidate validation was rerun after the gate change and passed, including the 94 focused release-policy tests, disposable PostgreSQL regressions, frontend tests/typecheck/build, repository lint/type checks, scope/budget, shell syntax, and diff checks. Current reviewed business-tree fingerprint: `ba154a93f3a27bc0fb90e241d923738107c8e8fd10db344baadb46afc65a290b` on base commit `d7eaf589da609dcdab92f7aefea16441b046ba77`. The unowned `uv.lock` remains unchanged and excluded. The earlier DAG status mismatch was corrected: exact-head CI is now the active task, and the production-copy rehearsal is pending that CI and a safe storage window.
