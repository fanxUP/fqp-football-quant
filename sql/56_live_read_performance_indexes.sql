-- The betting terminal reads the latest open option for every currently
-- sellable match. Keep the response index-only as the odds history grows.
CREATE INDEX IF NOT EXISTS idx_odds_open_latest_covering
    ON official_odds_snapshots (
        match_id,
        play_type,
        option_code,
        snapshot_time DESC
    )
    INCLUDE (option_name, sp_value, handicap, is_single_allowed)
    WHERE is_open = true;

-- Evaluation history only accepts independently calculated, validated
-- predictions. Restrict the index to that evidence boundary so recent-match
-- joins do not scan the complete prediction archive.
CREATE INDEX IF NOT EXISTS idx_predictions_independent_match_latest
    ON model_predictions (
        match_id,
        model_version_id,
        play_type,
        option_code,
        predict_time DESC,
        id DESC
    )
    INCLUDE (model_probability)
    WHERE model_probability IS NOT NULL
      AND validation_status = 'valid'
      AND COALESCE(
          (uncertainty_reason ->> 'model_independent')::boolean,
          false
      ) = true;
