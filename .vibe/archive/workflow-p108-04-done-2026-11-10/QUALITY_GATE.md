# P108-04 quality gate

Run the focused P108-04 fixed-response and player-observation tests against the explicit loopback PostgreSQL 16 fixture; require all tests to execute without skip. Run Ruff check/format, mypy, scope/budget, independent code and migration review, security review, then exact-head GitHub CI. There is no migration; the migration review must confirm reuse of migration 107 is safe. No provider, production DB, data import, scheduler, model change, or deployment is in scope.
