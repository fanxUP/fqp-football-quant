# P119 Plan

1. Preserve legacy P118 files in `archive/pre-v4-p118-2026-10-21/` with SHA-256 manifest.
2. Initialize V4 controls against main baseline `657d82d671fe0842c8c7c27c8cd85c9b509caa1e`.
3. Run the auth ACL regression and Ruff, then check scope, budget, and regression gates.
4. Record independent review and final-head GitHub CI.
5. Run the V4 merge gate, merge PR #23, and deploy the merged revision with the server release runner.
6. Verify server revision, service health, unauthenticated API behavior, and password login using private test credentials if available.
