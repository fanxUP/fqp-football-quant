-- Evaluation counts one eligible pre-match observation per match/model name.
-- Seek version identities and their latest scored SPF row before merging names;
-- repeated historical snapshots must not require a global evaluation sort.
-- Before production apply, measure build time/space and write-lock impact on a
-- data copy. If necessary, prebuild this exact index CONCURRENTLY outside the
-- atomic migration transaction and verify its definition and validity first.
CREATE INDEX IF NOT EXISTS idx_mem_identity_latest_scored_spf
    ON market_efficiency_metrics (
        match_id, model_version_id, snapshot_time DESC, id DESC
    )
    WHERE play_type = 'spf'
      AND brier_score IS NOT NULL
      AND model_version_id IS NOT NULL;
