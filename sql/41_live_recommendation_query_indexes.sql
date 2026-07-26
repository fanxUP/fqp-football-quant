-- Keep the live recommendation path responsive as prediction and odds history grow.
CREATE INDEX IF NOT EXISTS idx_predictions_live_latest
    ON model_predictions (
        match_id,
        model_version_id,
        play_type,
        option_code,
        predict_time DESC,
        id DESC
    )
    WHERE odds_snapshot_id IS NOT NULL
      AND feature_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_odds_handicap_latest
    ON official_odds_snapshots (match_id, play_type, snapshot_time DESC)
    WHERE handicap IS NOT NULL;
