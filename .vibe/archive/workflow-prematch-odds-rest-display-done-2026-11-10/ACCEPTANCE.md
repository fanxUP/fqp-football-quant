# Acceptance: prematch schedule and traditional market references

- Target time follows the authorized kickoff/cutoff rule, including equality, next-day and year-boundary cases.
- Official schedule notices cover postponements, cancellations and temporary additions; concurrent notice updates fence scheduled predictions.
- Model runs use current eligible quotes, preserve fixture identity and do not publish after an input supersession.
- Traditional pool market references are pre-kickoff-only, tied to one exact fixture and current bookmaker quote, separately labeled, and protected after publication.
- Local PostgreSQL tests prove both migrations, restricted `fqp` ACL/business paths, published-reference protection and data-preserving rollback refusal.
- Frontend tests/typecheck/build, targeted backend regression, Ruff and GitHub CI pass.
- `main` is the only branch; publish to GitHub, deploy to `100.121.47.26` without a database backup, then verify migrations, release identity, services, readiness and protected critical paths.

## Follow-up: odds movement during sales rest

- During sales rest, the current odds index and current odds response count the same upcoming scheduled official matches that have at least one saved canonical Sporttery odds snapshot.
- Current odds results still return each selected play's full stored snapshot series and preserve the snapshot timestamps.
- Open-sales matching and historical-date filtering retain their previous eligibility rules.
- The page explains sales rest when saved odds are visible, and shows a useful empty message when no eligible snapshot exists.
- Targeted backend/frontend regressions, isolated PostgreSQL behavior checks, frontend typecheck/build, exact-main CI and production read-only smoke pass.
- Deploy the exact GitHub `main` SHA to `100.121.47.26` without creating a database backup or writing business data.
