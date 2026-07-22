-- 03_model_research_schema.sql
CREATE TABLE IF NOT EXISTS research_papers (
    id BIGSERIAL PRIMARY KEY,
    paper_key VARCHAR(128) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    authors TEXT,
    year INT,
    doi VARCHAR(256),
    url TEXT,
    model_area VARCHAR(128),
    notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_versions (
    id BIGSERIAL PRIMARY KEY,
    model_name VARCHAR(128) NOT NULL,
    model_type VARCHAR(64) NOT NULL,
    version VARCHAR(64) NOT NULL,
    paper_key VARCHAR(128),
    training_start_date DATE,
    training_end_date DATE,
    training_window_start DATE,
    training_window_end DATE,
    feature_set_version VARCHAR(64),
    parameters_json JSONB,
    description TEXT,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(model_name, version)
);

CREATE TABLE IF NOT EXISTS odds_probability_conversions (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    market_id BIGINT REFERENCES official_markets(id),
    odds_snapshot_group_time TIMESTAMP NOT NULL,
    play_type VARCHAR(32) NOT NULL,
    method_name VARCHAR(64) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    raw_implied_probability NUMERIC(10,6),
    converted_probability NUMERIC(10,6),
    overround NUMERIC(10,6),
    method_params JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS score_distribution_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    model_version_id BIGINT NOT NULL REFERENCES model_versions(id),
    prediction_time TIMESTAMP NOT NULL,
    lambda_home NUMERIC(10,6),
    lambda_away NUMERIC(10,6),
    rho NUMERIC(10,6),
    home_win_prob NUMERIC(10,6),
    draw_prob NUMERIC(10,6),
    away_win_prob NUMERIC(10,6),
    score_matrix JSONB NOT NULL,
    method_name VARCHAR(64),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    model_version_id BIGINT NOT NULL REFERENCES model_versions(id),
    odds_snapshot_id BIGINT REFERENCES official_odds_snapshots(id),
    feature_snapshot_id BIGINT,
    predict_time TIMESTAMP NOT NULL,
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    model_probability NUMERIC(10,6),
    market_probability NUMERIC(10,6),
    probability_lower_bound NUMERIC(10,6),
    probability_upper_bound NUMERIC(10,6),
    uncertainty_score NUMERIC(10,6),
    adjusted_probability NUMERIC(10,6),
    fair_odds NUMERIC(10,4),
    ev NUMERIC(10,6),
    confidence_score NUMERIC(10,4),
    risk_score NUMERIC(10,4),
    uncertainty_reason JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_committee_votes (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    prediction_time TIMESTAMP NOT NULL,
    model_version_id BIGINT REFERENCES model_versions(id),
    model_name VARCHAR(128),
    model_probability NUMERIC(10,6),
    vote_direction VARCHAR(32),
    vote_weight NUMERIC(10,6),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_efficiency_metrics (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    model_version_id BIGINT REFERENCES model_versions(id),
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    snapshot_time TIMESTAMP NOT NULL,
    official_sp NUMERIC(10,4),
    market_probability NUMERIC(10,6),
    model_probability NUMERIC(10,6),
    probability_gap NUMERIC(10,6),
    fair_odds NUMERIC(10,4),
    ev NUMERIC(10,6),
    clv_score NUMERIC(10,6),
    favourite_longshot_score NUMERIC(10,6),
    brier_score NUMERIC(10,6),
    log_loss NUMERIC(10,6),
    rps NUMERIC(10,6),
    market_signal_level VARCHAR(32),
    created_at TIMESTAMP DEFAULT now()
);
