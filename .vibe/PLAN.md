# Prematch scheduling and traditional market references

Task: `PREMATCH-SCHEDULE-MARKET-REFERENCE-20261109` on the existing `main` branch.

Implement and release the agreed prediction-time rules: use kickoff minus two hours when kickoff is before the official Sporttery cutoff; otherwise use 20:30 China Standard Time. Reconcile official fixture changes and temporary additions before a scheduled run, and prevent stale odds or changed schedule inputs from being published. For traditional lottery issues, collect a pre-kickoff Titan007 1X2 market reference as a separate review signal; it must not replace model predictions or official results.

The release adds migrations 132 and 133 as one pinned ordered pair. User authorized submission and server deployment without creating a database backup. Production migration is permitted only after isolated PostgreSQL rehearsal and exact-head CI. No unrelated model redesign or data backfill is in scope.
