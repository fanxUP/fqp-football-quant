-- 02_governance_schema.sql
-- NOTE: teams and team_aliases are now defined in 08_season_team_database.sql
--       match_feature_snapshots is now defined in 12_match_feature_snapshots.sql
--       Only leagues/league_aliases remain in this file.

CREATE TABLE IF NOT EXISTS leagues (
    id BIGSERIAL PRIMARY KEY,
    canonical_name VARCHAR(128) NOT NULL UNIQUE,
    country VARCHAR(64),
    level INT,
    league_strength NUMERIC(10,4),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS league_aliases (
    id BIGSERIAL PRIMARY KEY,
    league_id BIGINT REFERENCES leagues(id),
    source_name VARCHAR(64),
    alias_name VARCHAR(128) NOT NULL,
    confidence NUMERIC(10,4) DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(source_name, alias_name)
);
