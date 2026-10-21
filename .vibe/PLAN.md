# P119 Plan

1. Preserve legacy P118 files in `archive/pre-v4-p118-2026-10-21/` with SHA-256 manifest.
2. Initialize V4 controls against main baseline `657d82d671fe0842c8c7c27c8cd85c9b509caa1e`.
3. Run the auth ACL regression and Ruff, then check scope, budget, and regression gates.
4. Record independent review and final-head GitHub CI.
5. Run the V4 merge gate, merge PR #23, and deploy the merged revision with the server release runner.
6. Verify server revision, service health, unauthenticated API behavior, and password login using private test credentials if available.

# P120 Plan

1. Preserve the completed P119 terminal state and start a separate V4 workflow for the frontend publisher.
2. Merge the latest `main` into the existing PR #22 branch, retain the deploy runner change, and replace its legacy P119 metadata with P120 controls.
3. Extract the inline publisher into `ops/server/publish_frontend.py` and add isolated temporary-filesystem regression coverage.
4. Run the configured V4 evidence command, shell syntax check, scope, budget and regression gates. Review the exact final diff for filesystem, shell and rollback safety.
5. Push the updated PR #22 head, wait for configured GitHub CI, obtain independent read-only review, and run the repository V4 merge wrapper against the exact head.
6. Merge PR #22 only after the gate is ready. Prepare the server release plan, record rollback and migration/dependency status, deploy the exact merged `main` SHA, and verify services, readiness, frontend, protected route and recent logs.
7. Record post-deployment evidence and transition the V4 workflow to `DONE` only after all checks pass.
