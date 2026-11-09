# Acceptance: prematch schedule and traditional market references

- Target time follows the authorized kickoff/cutoff rule, including equality, next-day and year-boundary cases.
- Official schedule notices cover postponements, cancellations and temporary additions; concurrent notice updates fence scheduled predictions.
- Model runs use current eligible quotes, preserve fixture identity and do not publish after an input supersession.
- Traditional pool market references are pre-kickoff-only, tied to one exact fixture and current bookmaker quote, separately labeled, and protected after publication.
- Local PostgreSQL tests prove both migrations, restricted `fqp` ACL/business paths, published-reference protection and data-preserving rollback refusal.
- Frontend tests/typecheck/build, targeted backend regression, Ruff and GitHub CI pass.
- `main` is the only branch; publish to GitHub, deploy to `100.121.47.26` without a database backup, then verify migrations, release identity, services, readiness and protected critical paths.
