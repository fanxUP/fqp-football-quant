-- 10_injury_stadium_weather_database.sql
-- 伤停、旅行、天气数据库

CREATE TABLE IF NOT EXISTS player_availability_snapshots (
    id BIGSERIAL PRIMARY KEY,
    player_id BIGINT NOT NULL REFERENCES players(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    snapshot_time TIMESTAMP NOT NULL,
    availability_status VARCHAR(32) NOT NULL,
    injury_type VARCHAR(128),
    injury_body_part VARCHAR(64),
    is_suspended BOOLEAN DEFAULT false,
    suspension_reason VARCHAR(128),
    expected_return_date DATE,
    source_name VARCHAR(64),
    source_url TEXT,
    source_confidence NUMERIC(10,4),
    recent_minutes_share NUMERIC(10,6),
    team_market_value_share NUMERIC(10,6),
    position_importance_score NUMERIC(10,4),
    replacement_quality_score NUMERIC(10,4),
    absence_impact_score NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS match_travel_features (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL,
    home_team_id BIGINT NOT NULL REFERENCES teams(id),
    away_team_id BIGINT NOT NULL REFERENCES teams(id),
    stadium_id BIGINT REFERENCES stadiums(id),
    snapshot_time TIMESTAMP NOT NULL,
    home_travel_distance_km NUMERIC(10,2),
    away_travel_distance_km NUMERIC(10,2),
    timezone_diff NUMERIC(5,2),
    altitude_diff_m NUMERIC(10,2),
    home_rest_days INT,
    away_rest_days INT,
    home_matches_last_7_days INT,
    away_matches_last_7_days INT,
    home_matches_last_14_days INT,
    away_matches_last_14_days INT,
    home_consecutive_away_games INT,
    away_consecutive_away_games INT,
    home_travel_fatigue_score NUMERIC(10,4),
    away_travel_fatigue_score NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS match_weather_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL,
    stadium_id BIGINT REFERENCES stadiums(id),
    snapshot_time TIMESTAMP NOT NULL,
    forecast_for_time TIMESTAMP NOT NULL,
    temperature_2m NUMERIC(8,2),
    apparent_temperature NUMERIC(8,2),
    relative_humidity_2m NUMERIC(8,2),
    precipitation NUMERIC(8,2),
    rain NUMERIC(8,2),
    snowfall NUMERIC(8,2),
    wind_speed_10m NUMERIC(8,2),
    wind_gusts_10m NUMERIC(8,2),
    surface_pressure NUMERIC(8,2),
    cloud_cover NUMERIC(8,2),
    weather_code VARCHAR(32),
    weather_impact_score NUMERIC(10,4),
    tempo_penalty_score NUMERIC(10,4),
    goal_expectation_adjustment NUMERIC(10,6),
    uncertainty_adjustment NUMERIC(10,6),
    source_name VARCHAR(64),
    source_confidence NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_availability_player_snap ON player_availability_snapshots(player_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_availability_team_snap ON player_availability_snapshots(team_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_travel_match_snap ON match_travel_features(match_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_weather_match_snap ON match_weather_snapshots(match_id, snapshot_time);
