-- Glicko-2 评分：保留评分偏差与波动率，以便赛前识别新赛季的不确定性。

CREATE TABLE IF NOT EXISTS team_glicko2_ratings (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    team_name VARCHAR(200),
    season VARCHAR(128),
    rating DOUBLE PRECISION NOT NULL DEFAULT 1500.0,
    rating_deviation DOUBLE PRECISION NOT NULL DEFAULT 350.0,
    volatility DOUBLE PRECISION NOT NULL DEFAULT 0.06,
    matches_played INTEGER NOT NULL DEFAULT 0,
    last_match_date DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (team_id, season)
);

CREATE INDEX IF NOT EXISTS idx_team_glicko2_team_season
    ON team_glicko2_ratings (team_id, season);

CREATE TABLE IF NOT EXISTS glicko2_update_logs (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL UNIQUE REFERENCES official_matches(id) ON DELETE CASCADE,
    home_team_id BIGINT NOT NULL REFERENCES teams(id),
    away_team_id BIGINT NOT NULL REFERENCES teams(id),
    home_rating_before DOUBLE PRECISION NOT NULL,
    away_rating_before DOUBLE PRECISION NOT NULL,
    home_deviation_before DOUBLE PRECISION NOT NULL,
    away_deviation_before DOUBLE PRECISION NOT NULL,
    home_rating_after DOUBLE PRECISION NOT NULL,
    away_rating_after DOUBLE PRECISION NOT NULL,
    home_deviation_after DOUBLE PRECISION NOT NULL,
    away_deviation_after DOUBLE PRECISION NOT NULL,
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    season VARCHAR(128),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON team_glicko2_ratings TO fqp;
GRANT SELECT, INSERT, UPDATE, DELETE ON glicko2_update_logs TO fqp;
GRANT USAGE, SELECT ON SEQUENCE team_glicko2_ratings_id_seq TO fqp;
GRANT USAGE, SELECT ON SEQUENCE glicko2_update_logs_id_seq TO fqp;

INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES (
    'glicko2_rating',
    'uncertainty_aware_strength_rating',
    '1.0.0',
    'Glicko-2 strength rating with rating deviation and volatility. Starts in shadow mode until evaluation gates pass.',
    '{"rollout_mode":"shadow"}'::jsonb,
    true
)
ON CONFLICT (model_name, version) DO NOTHING;
