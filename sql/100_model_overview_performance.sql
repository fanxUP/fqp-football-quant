-- The model overview counts distinct validated matches for every current
-- version. Keep that audit query index-only as prediction history grows.
CREATE INDEX IF NOT EXISTS idx_predictions_model_valid_match_covering
    ON model_predictions (model_version_id, match_id, predict_time DESC)
    WHERE validation_status = 'valid';
