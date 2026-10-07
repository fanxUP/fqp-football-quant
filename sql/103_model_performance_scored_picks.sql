-- Compact, rebuildable per-match outcomes for the model performance chart.
CREATE TABLE IF NOT EXISTS model_performance_scored_picks (
    match_id BIGINT NOT NULL REFERENCES official_matches(id) ON DELETE CASCADE,
    business_date DATE NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    play_type VARCHAR(32) NOT NULL,
    is_correct SMALLINT NOT NULL CHECK (is_correct IN (0, 1)),
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (match_id, model_name, play_type)
);

CREATE INDEX IF NOT EXISTS idx_model_performance_scored_picks_history
    ON model_performance_scored_picks (business_date, play_type, model_name, match_id)
    INCLUDE (is_correct);

CREATE TABLE IF NOT EXISTS model_performance_scored_picks_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    full_refreshed_at TIMESTAMPTZ,
    last_refreshed_at TIMESTAMPTZ
);

INSERT INTO model_performance_scored_picks_state (singleton)
VALUES (TRUE)
ON CONFLICT (singleton) DO NOTHING;
