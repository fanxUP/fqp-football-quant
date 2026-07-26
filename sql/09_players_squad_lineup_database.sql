-- 09_players_squad_lineup_database.sql
-- 球员、赛季阵容、预测首发、官方首发数据库

CREATE TABLE IF NOT EXISTS players (
    id BIGSERIAL PRIMARY KEY,
    player_code VARCHAR(64) UNIQUE,
    player_name_cn VARCHAR(128),
    player_name_en VARCHAR(128),
    birth_date DATE,
    nationality VARCHAR(64),
    primary_position VARCHAR(32),
    secondary_positions JSONB,
    preferred_foot VARCHAR(16),
    height_cm NUMERIC(6,2),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS player_aliases (
    id BIGSERIAL PRIMARY KEY,
    player_id BIGINT NOT NULL REFERENCES players(id),
    source_name VARCHAR(64) NOT NULL,
    alias_name VARCHAR(128) NOT NULL,
    language VARCHAR(16),
    confidence NUMERIC(10,4) DEFAULT 1.0,
    is_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE (source_name, alias_name)
);

CREATE TABLE IF NOT EXISTS player_season_profiles (
    id BIGSERIAL PRIMARY KEY,
    player_id BIGINT NOT NULL REFERENCES players(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    shirt_number VARCHAR(16),
    position VARCHAR(32),
    role_type VARCHAR(32),
    market_value NUMERIC(16,2),
    market_value_currency VARCHAR(16) DEFAULT 'EUR',
    market_value_rank_in_team INT,
    appearances INT,
    starts INT,
    minutes_played INT,
    goals INT,
    assists INT,
    yellow_cards INT,
    red_cards INT,
    recent_5_starts INT,
    recent_5_minutes INT,
    recent_10_starts INT,
    recent_10_minutes INT,
    is_key_player BOOLEAN DEFAULT false,
    key_player_score NUMERIC(10,4),
    starter_probability NUMERIC(10,6),
    contract_until DATE,
    loan_status VARCHAR(32),
    data_source VARCHAR(64),
    data_confidence NUMERIC(10,4),
    snapshot_time TIMESTAMP NOT NULL,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_squad_snapshots (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    snapshot_time TIMESTAMP NOT NULL,
    available_players_count INT,
    injured_players_count INT,
    suspended_players_count INT,
    doubtful_players_count INT,
    available_market_value NUMERIC(16,2),
    unavailable_market_value NUMERIC(16,2),
    unavailable_value_ratio NUMERIC(10,6),
    key_absence_count INT,
    goalkeeper_available BOOLEAN,
    center_back_available_count INT,
    striker_available_count INT,
    squad_health_score NUMERIC(10,4),
    squad_depth_score NUMERIC(10,4),
    data_confidence NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS match_lineup_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    snapshot_time TIMESTAMP NOT NULL,
    lineup_type VARCHAR(32) NOT NULL,
    source_name VARCHAR(64),
    source_confidence NUMERIC(10,4),
    formation VARCHAR(32),
    formation_changed BOOLEAN,
    goalkeeper_changed BOOLEAN,
    center_back_pair_changed BOOLEAN,
    starting_11_market_value NUMERIC(16,2),
    starting_11_avg_age NUMERIC(6,2),
    starting_11_recent_minutes INT,
    starting_11_key_player_count INT,
    bench_market_value NUMERIC(16,2),
    bench_strength_score NUMERIC(10,4),
    lineup_strength_score NUMERIC(10,4),
    rotation_risk_score NUMERIC(10,4),
    lineup_uncertainty_score NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS match_lineup_players (
    id BIGSERIAL PRIMARY KEY,
    lineup_snapshot_id BIGINT NOT NULL REFERENCES match_lineup_snapshots(id) ON DELETE CASCADE,
    player_id BIGINT NOT NULL REFERENCES players(id),
    is_starting BOOLEAN DEFAULT false,
    is_substitute BOOLEAN DEFAULT false,
    position VARCHAR(32),
    tactical_role VARCHAR(64),
    market_value NUMERIC(16,2),
    recent_minutes INT,
    key_player_score NUMERIC(10,4),
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_player_profiles_player_snap ON player_season_profiles(player_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_player_profiles_team_snap ON player_season_profiles(team_id, competition_season_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_lineup_match_team_snap ON match_lineup_snapshots(match_id, team_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_lineup_players_snapshot ON match_lineup_players(lineup_snapshot_id);
