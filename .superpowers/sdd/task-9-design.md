# Task 9: Accelerate model performance history

## Objective and risk

Reduce waits on `/api/analysis/evaluation/history` without changing how the
curve is scored or the JSON shape. Persist the small set of scored picks so
requests no longer rank the full prediction history. The rollout adds one
derived-data table and one background backfill job; it adds no dependency or
external service.

## Design

- Store one scored top pick per match, model, and play type in PostgreSQL. The
  initial scheduler run backfills the API's maximum 1,095-day window; later
  runs recalculate recently changed results, with a complete reconciliation at
  least once every seven days.
- Keep the current full query as a fallback until the backfill completes or if
  the migration has not been applied.
- The scheduled refresh checks that both derived tables exist and reports a
  harmless skip until the migration is applied.
- Compute rolling windows and sample summaries from the compact scored-picks
  table, preserving the current response.
- Use the existing Redis service as a process-shared response cache keyed by
  `window` and `days`.
- Treat entries up to 2 minutes old as fresh. For entries up to 10 minutes old,
  return the cached response immediately and start one background refresh, with
  a Redis lock preventing duplicate refreshes across backend processes.
- On a cold miss, calculate through the compact table when it is ready; otherwise
  use the current query and populate the cache.
- If Redis is unavailable or its data is invalid, compute directly from
  PostgreSQL. Keep the API response contract unchanged.
- Preserve a versioned cache key so a future scoring-semantic change can
  invalidate old entries.

The new PostgreSQL table contains rebuildable derived data. Its migration only
creates the empty table, state row, and lookup index; the expensive backfill
runs separately under the scheduler and commits atomically. Recent updates are
replayed every 30 minutes; the full reconciliation catches older corrections
and late prediction imports weekly. The paired down migration drops only these
derived tables; source predictions and results remain intact and can rebuild
the cache after the forward migration is reapplied.

For production rollout, inspect and dry-run the migration on a database copy
after taking the normal database backup. A code rollback can leave the derived
table unused; it does not modify source prediction or result rows.

## Plan and acceptance

| Plan | Acceptance |
| --- | --- |
| P1. Add a derived scored-picks table and atomic full backfill/recent refresh. | A1. The initial run populates the supported history range; subsequent runs replace only affected recent matches. |
| P2. Read rolling history from the compact table after initial backfill, retaining the existing SQL fallback. | A2. Before the backfill completes, history still returns through the current query; after completion, aggregation reads only scored picks. |
| P3. Add shared Redis caching and endpoint integration. | A3. Repeated requests avoid PostgreSQL; Redis failure falls back to the available SQL path. |
| P4. Register a scheduled refresh and keep public behavior unchanged. | A4. No dependency or response contract change is introduced; the cache table remains internal and rebuildable. |

## Work DAG

```text
P1 migration and refresh job ──> P2 compact query path ──┐
                                                        ├── P4 scope review
P3 shared Redis cache ──────────────────────────────────┘
```

## Non-goals

Production migration execution/deployment, frontend changes, and unrelated
database or query changes.
