-- 08_season_team_database.sql
-- 赛季、赛事、球队、积分榜、球队赛季画像数据库
-- PostgreSQL 14+

CREATE TABLE IF NOT EXISTS seasons (
    id BIGSERIAL PRIMARY KEY,
    season_code VARCHAR(32) NOT NULL UNIQUE,
    season_name VARCHAR(64) NOT NULL,
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS competitions (
    id BIGSERIAL PRIMARY KEY,
    competition_code VARCHAR(64) NOT NULL UNIQUE,
    competition_name_cn VARCHAR(128),
    competition_name_en VARCHAR(128),
    country VARCHAR(64),
    competition_type VARCHAR(32) NOT NULL,
    level INT,
    is_cup BOOLEAN DEFAULT false,
    is_league BOOLEAN DEFAULT false,
    has_group_stage BOOLEAN DEFAULT false,
    has_knockout_stage BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS competition_seasons (
    id BIGSERIAL PRIMARY KEY,
    competition_id BIGINT NOT NULL REFERENCES competitions(id),
    season_id BIGINT NOT NULL REFERENCES seasons(id),
    stage_format VARCHAR(64),
    total_teams INT,
    total_rounds INT,
    promotion_slots INT,
    relegation_slots INT,
    continental_slots INT,
    playoff_slots INT,
    point_win INT DEFAULT 3,
    point_draw INT DEFAULT 1,
    point_loss INT DEFAULT 0,
    ranking_rules JSONB,
    schedule_format JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE (competition_id, season_id)
);

CREATE TABLE IF NOT EXISTS stadiums (
    id BIGSERIAL PRIMARY KEY,
    stadium_name VARCHAR(128) NOT NULL,
    city VARCHAR(128),
    country VARCHAR(64),
    latitude NUMERIC(10,6),
    longitude NUMERIC(10,6),
    altitude_m NUMERIC(10,2),
    capacity INT,
    pitch_type VARCHAR(32),
    roof_type VARCHAR(32),
    timezone VARCHAR(64),
    data_source VARCHAR(64),
    data_confidence NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams (
    id BIGSERIAL PRIMARY KEY,
    team_code VARCHAR(64) UNIQUE,
    team_name_cn VARCHAR(128),
    team_name_en VARCHAR(128),
    short_name VARCHAR(64),
    country VARCHAR(64),
    city VARCHAR(128),
    founded_year INT,
    official_website TEXT,
    primary_stadium_id BIGINT REFERENCES stadiums(id),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_aliases (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    source_name VARCHAR(64) NOT NULL,
    alias_name VARCHAR(128) NOT NULL,
    language VARCHAR(16),
    confidence NUMERIC(10,4) DEFAULT 1.0,
    is_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE (source_name, alias_name)
);

CREATE TABLE IF NOT EXISTS team_stadium_history (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    stadium_id BIGINT NOT NULL REFERENCES stadiums(id),
    start_date DATE,
    end_date DATE,
    is_primary BOOLEAN DEFAULT true,
    is_temporary BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS season_standings_snapshots (
    id BIGSERIAL PRIMARY KEY,
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),
    snapshot_time TIMESTAMP NOT NULL,
    round_no INT,
    rank INT,
    played INT,
    won INT,
    drawn INT,
    lost INT,
    goals_for INT,
    goals_against INT,
    goal_difference INT,
    points INT,
    home_points INT,
    away_points INT,
    title_race_score NUMERIC(10,4),
    continental_race_score NUMERIC(10,4),
    promotion_pressure_score NUMERIC(10,4),
    relegation_pressure_score NUMERIC(10,4),
    qualification_pressure_score NUMERIC(10,4),
    no_pressure_score NUMERIC(10,4),
    source_name VARCHAR(64),
    source_confidence NUMERIC(10,4),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_season_profiles (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    squad_size INT,
    avg_age NUMERIC(6,2),
    foreign_players INT,
    national_team_players INT,
    total_market_value NUMERIC(16,2),
    avg_market_value NUMERIC(16,2),
    median_market_value NUMERIC(16,2),
    top_5_market_value NUMERIC(16,2),
    top_11_market_value NUMERIC(16,2),
    squad_depth_value NUMERIC(16,2),
    league_market_value_rank INT,
    league_market_value_percentile NUMERIC(10,6),
    preferred_formation VARCHAR(32),
    alternative_formations JSONB,
    home_strength_score NUMERIC(10,4),
    away_strength_score NUMERIC(10,4),
    attack_strength_score NUMERIC(10,4),
    defense_strength_score NUMERIC(10,4),
    midfield_strength_score NUMERIC(10,4),
    squad_depth_score NUMERIC(10,4),
    manager_name VARCHAR(128),
    manager_start_date DATE,
    manager_tactical_style VARCHAR(64),
    data_source VARCHAR(64),
    data_confidence NUMERIC(10,4),
    snapshot_time TIMESTAMP NOT NULL,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE (team_id, competition_season_id, snapshot_time)
);

CREATE INDEX IF NOT EXISTS idx_competition_seasons_season ON competition_seasons(season_id);
CREATE INDEX IF NOT EXISTS idx_standings_comp_snap ON season_standings_snapshots(competition_season_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_team_profiles_team_snap ON team_season_profiles(team_id, competition_season_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_team_aliases_source_alias ON team_aliases(source_name, alias_name);
