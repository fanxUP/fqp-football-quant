# Independent review: prematch scheduling and market references

Review type: read-only release review. The review covered the complete 44-path business diff, including both additive migrations, the migration release gate, prediction scheduling, official notice parsing, Titan007 reference collection, and catalog UI integration.

## Outcome

PASS. No blocker or major finding remains. The only minor semantic point was whether a match/play task should remain pending until every model has published. The implementation defines completion as publishing at least one complete prediction group; unavailable model groups remain visible in the run audit and do not cause a one-shot scheduled task to run forever. The code documentation now records this meaning.

## Reviewed boundaries

- Prediction target is kickoff minus two hours when kickoff is at or before the official cutoff; otherwise it is 20:30 Asia/Shanghai, moved to the previous evening if 20:30 would not precede kickoff.
- Notice updates and prediction writes share an advisory fence; each result group is rechecked before publication.
- Late additions, changed kickoffs, withdrawals, stale odds, ambiguous identities and mismatched market schedules fail closed.
- Traditional-pool market references are separated from model predictions, require one exact unstarted fixture and a fresh complete 1X2 quote, and become protected after publication.
- Migrations 132 and 133 are accepted only as the exact ordered pinned pair; their down migrations refuse to discard schedule receipts, sparse snapshots or published references.
- No new public endpoint, package or service is introduced. The catalog change is additive.

Reviewer did not modify code, run tests, or access production. Local test, isolated PostgreSQL rehearsal, exact-head CI and production verification remain separately evidenced.

## Test fixture follow-up

The first follow-up confirmed that the unique numeric Sporttery IDs are checked against `official_matches`, and that test-only selection filtering preserves the production selector and final fence. A second follow-up confirmed that the generated `issue_no` is checked against the globally unique `football_pool_issues.issue_no` before writes. The only residual minor caveat is a check/insert race if two copies of this one test run simultaneously against the same isolated database; ordinary sequential reruns and stale queued fixtures are handled, and production behavior is unchanged.

## Exact-head CI fixture follow-up

Exact-head CI found that the isolated match-review fixture omitted `official_odds_snapshots.raw_hash`, a column present in the production schema and read by the reviewed odds-reference query. The test fixture now declares that column. This follow-up changes no production code; the previously failing isolated test passes locally, and full CI is being rerun on the updated main commit.

## Official schedule writer lock-wait follow-up

On 2026-11-09, an independent read-only review examined the bounded advisory-lock wait added to both official schedule write paths. Outcome: PASS with one MINOR test-cleanup finding. The writer temporarily uses a 45-second bound only for the shared schedule advisory lock, then restores the prior transaction-local `lock_timeout`; the value is parameterized and stays below the production 60-second statement timeout. Both writers preserve the existing lock order and prediction fencing. The reviewer found no production blocker or major issue.

The reviewer noted that the integration test should assert its writer thread has terminated before cleanup. That assertion is now present. The isolated PostgreSQL regression first reproduced the old 2-second failure, then passed with the fix; it also passed using the CI branch against a loopback `fqp_test` database. The review was read-only and did not connect to production.
