-- 01_core_official_schema.sql
-- 官方数据中台：赛程、玩法、赔率快照、赛果、采集日志
CREATE TABLE IF NOT EXISTS official_matches (
    id BIGSERIAL PRIMARY KEY,
    sport_type VARCHAR(32) NOT NULL DEFAULT 'football',
    business_date DATE NOT NULL,
    official_match_code VARCHAR(32) NOT NULL,
    source_match_id VARCHAR(64) NOT NULL,
    league_name VARCHAR(128) NOT NULL,
    home_team_name VARCHAR(128) NOT NULL,
    away_team_name VARCHAR(128) NOT NULL,
    kickoff_time TIMESTAMP NOT NULL,
    sale_stop_time TIMESTAMP,
    sale_status VARCHAR(32) DEFAULT 'unknown',
    match_status VARCHAR(32) DEFAULT 'scheduled',
    source_url TEXT,
    raw_hash VARCHAR(128),
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE (business_date, official_match_code),
    CONSTRAINT official_matches_display_code_format
        CHECK (official_match_code ~ '^周[一二三四五六日][0-9]{3}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_official_matches_source_match_id
    ON official_matches (source_match_id)
    WHERE source_match_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS official_markets (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    play_type VARCHAR(32) NOT NULL, -- spf/rqspf/bf/zjq/bqc/mixed (canonical codes)
    handicap NUMERIC(5,2),
    is_open BOOLEAN DEFAULT true,
    is_single_allowed BOOLEAN DEFAULT false,
    market_status VARCHAR(32) DEFAULT 'open',
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_official_markets_unique
    ON official_markets (match_id, play_type, COALESCE(handicap, 9999));

CREATE TABLE IF NOT EXISTS official_odds_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    market_id BIGINT REFERENCES official_markets(id),
    snapshot_time TIMESTAMP NOT NULL,
    snapshot_label VARCHAR(64),
    minutes_before_stop INT,
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    option_name VARCHAR(128) NOT NULL,
    sp_value NUMERIC(10,4) NOT NULL CHECK (sp_value > 0),
    handicap NUMERIC(5,2),
    is_open BOOLEAN DEFAULT true,
    is_single_allowed BOOLEAN DEFAULT false,
    raw_json JSONB,
    raw_hash VARCHAR(128),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS official_results (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    half_home_goals INT,
    half_away_goals INT,
    full_home_goals INT,
    full_away_goals INT,
    spf_result VARCHAR(16),
    rqspf_result VARCHAR(16),
    total_goals_result VARCHAR(16),
    score_result VARCHAR(32),
    half_full_result VARCHAR(32),
    result_status VARCHAR(32) DEFAULT 'pending',
    official_publish_time TIMESTAMP,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(match_id)
);

CREATE TABLE IF NOT EXISTS official_crawl_logs (
    id BIGSERIAL PRIMARY KEY,
    source_name VARCHAR(64) NOT NULL,
    crawl_type VARCHAR(64) NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status VARCHAR(32) NOT NULL,
    records_found INT DEFAULT 0,
    records_inserted INT DEFAULT 0,
    records_updated INT DEFAULT 0,
    error_message TEXT,
    raw_response_hash VARCHAR(128),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_source_health (
    id BIGSERIAL PRIMARY KEY,
    source_name VARCHAR(64) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    last_success_time TIMESTAMP,
    last_failure_time TIMESTAMP,
    failure_count INT DEFAULT 0,
    latency_ms INT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS official_collection_status (
    id BIGSERIAL PRIMARY KEY,
    business_date DATE NOT NULL,
    crawl_type VARCHAR(64) NOT NULL,
    source_name VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    source_url TEXT,
    source_artifact_path TEXT,
    source_artifact_hash VARCHAR(128),
    http_status INT,
    records_found INT DEFAULT 0,
    records_inserted INT DEFAULT 0,
    records_updated INT DEFAULT 0,
    error_message TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_official_collection_status_unique
    ON official_collection_status (
        business_date,
        crawl_type,
        source_name,
        COALESCE(source_artifact_hash, '')
    );
