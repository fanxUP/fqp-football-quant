# Aggregate release quality gate

Do not include or stage `uv.lock`. Run scope/budget/regression checks against baseline `main`. Require clean commits, complete local evidence, read-only independent review, security review, migration-copy rehearsal, and exact-head GitHub CI. Release may proceed only after the configured V4 preflight passes. After deployment, verify services, health, critical paths, logs/metrics, migration results and at least one natural scheduled refresh. Keep P107/A107 open until those production observations are recorded.
