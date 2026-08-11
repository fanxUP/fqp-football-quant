-- News Intelligence P4: isolated shadow predictions and outcome evaluation.
CREATE TABLE IF NOT EXISTS news_shadow_predictions (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    snapshot_id BIGINT NOT NULL REFERENCES match_news_snapshots(id),
    baseline_model_version_id BIGINT NOT NULL REFERENCES model_versions(id),
    baseline_predict_time TIMESTAMP NOT NULL,
    baseline_probabilities JSONB NOT NULL,
    shadow_probabilities JSONB NOT NULL,
    home_news_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    away_news_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    max_probability_shift NUMERIC(8,6) NOT NULL,
    shadow_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (match_id, snapshot_id, baseline_model_version_id, shadow_version)
);

CREATE INDEX IF NOT EXISTS idx_news_shadow_predictions_match
    ON news_shadow_predictions (match_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS news_shadow_evaluations (
    id BIGSERIAL PRIMARY KEY,
    shadow_prediction_id BIGINT NOT NULL UNIQUE
        REFERENCES news_shadow_predictions(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    actual_option VARCHAR(1) NOT NULL CHECK (actual_option IN ('3', '1', '0')),
    baseline_brier NUMERIC(12,9) NOT NULL,
    shadow_brier NUMERIC(12,9) NOT NULL,
    baseline_log_loss NUMERIC(12,9) NOT NULL,
    shadow_log_loss NUMERIC(12,9) NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_shadow_evaluations_match
    ON news_shadow_evaluations (match_id, evaluated_at DESC, id DESC);
