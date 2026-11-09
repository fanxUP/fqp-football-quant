# Acceptance: P107 aggregate candidate release readiness

**Status: PASS — completed 2026-11-09.**

- Production, GitHub `main`, and exact-head CI use `b605866d2757102185ad75d8174dbc8f91076674`; CI run [42514769523](https://github.com/fanxUP/fqp-football-quant/actions/runs/42514769523) passed both configured jobs.
- Production release marker and readiness checks passed. Natural aggregate run `237100` produced the count and summary from one snapshot; the dirty queue drained to zero.
- In the authenticated FQP session, Dashboard displayed 16,287,673 and `/api/dashboard/prediction-count` returned the same total. `/api/predictions?summary_only=true` returned a fresh summary of 278,317 predictions, 47,334 positive-EV predictions, 19 models, and average confidence 0.83283351608776. Its `summary_only` response intentionally contains no row payload.
- Both APIs report `data_as_of=2026-11-09T03:48:17.178628Z`; the consumer summary was not stale (age 971 seconds, threshold 2,700 seconds). The two totals use different documented scopes: `valid_prematch_history_v1` and `canonical_valid_prematch_history_v1`.
- Natural scheduling completed the catch-up, so the approved 10-minute scheduler pause and a manual refresh were unnecessary. This verification made no manual business-data writes.
- Earlier local regression, PostgreSQL rehearsal, security review, migration review, and independent code review evidence remains recorded in `.vibe/EVIDENCE.yaml`.
