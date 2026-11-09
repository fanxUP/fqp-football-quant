# Design

- Store immutable Sporttery schedule notices and a durable one-shot prematch task per match/play.
- Recompute target time from current kickoff and authoritative sales-window facts; run at kickoff minus two hours if kickoff precedes the cutoff, otherwise at 20:30 Asia/Shanghai.
- Serialize schedule writers, task selection and prediction publication with a PostgreSQL advisory lock; re-fence before each published prediction group so a late-added, postponed or withdrawn fixture cannot publish stale output.
- Capture only fresh, pre-kickoff odds for the scheduled prediction. Sparse market-only feature snapshots retain no fabricated team identity.
- Keep traditional-pool market references separate from model predictions, append-only after publication, and expose them as reference context in the shared fixture catalog.
- Migration downs refuse to discard any schedule receipt, sparse snapshot or published reference.
