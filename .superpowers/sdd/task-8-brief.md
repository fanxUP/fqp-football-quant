# Task 8: Reduce model performance history latency

## Objective

Make `/api/analysis/evaluation/history` return before the frontend aborts its request, while preserving the response shape and scoring behavior.

## Evidence

- The production query took 17.00 seconds and returned 2,328 points across 57 samples.
- The frontend aborts general requests after 15 seconds.
- Production `EXPLAIN ANALYZE` took 29.95 seconds, sorted about 3.8 million prediction rows, spilled roughly 260 MB of sort data to disk, and applied the confirmed-result filter after ranking.
- The lateral handicap lookup ran 14,474 times, including rows for non-`rqspf` play types.

## Plan and acceptance

1. Apply the final/confirmed official-result filter before prediction ranking and carry the result fields through the query. The result is unique per match, so this preserves the selected prediction and output semantics.
2. Resolve `rqspf` picks separately and look up a handicap only when the official `rqspf_result` is missing.
3. Give this history endpoint a 30-second client timeout as a bounded fallback for normal database variance and future growth.
4. Keep the JSON response contract unchanged; add no schema migration or dependency.

## Acceptance criteria

- Only matches with final or confirmed results enter the expensive prediction ranking path.
- Only `rqspf` picks with a missing official handicap result query snapshots.
- Point values, sample counts, rolling window, supported play types, and response fields retain their current semantics.
- The model history endpoint has a 30-second timeout; other API timeouts stay unchanged.

## Work DAG

```text
production plan evidence
        |
        v
early settled-match filtering -----> split handicap resolution
        |                                      |
        +-------------------+------------------+
                            v
                 endpoint-specific timeout
                            |
                            v
                 scope and diff review
```
