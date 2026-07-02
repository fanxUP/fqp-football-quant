-- 07_schema_migration_fixes.sql
-- Migrates databases that were initialized with 02_governance_schema.sql's
-- older versions of teams, team_aliases, and match_feature_snapshots
-- to the canonical 08 + 12 definitions.
--
-- Safe to run on fresh databases (all statements use IF NOT EXISTS / IF EXISTS).

-- -------------------------------------------------------------------
-- teams: if 02's version exists (has name_cn instead of team_name_cn),
-- migrate to 08's definition
-- -------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'teams' AND column_name = 'name_cn'
    ) THEN
        -- 02's table exists; add 08 columns
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS team_code VARCHAR(64);
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS team_name_cn VARCHAR(128);
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS team_name_en VARCHAR(128);
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS short_name VARCHAR(64);
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS city VARCHAR(128);
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS founded_year INT;
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS official_website TEXT;
        ALTER TABLE teams ADD COLUMN IF NOT EXISTS primary_stadium_id BIGINT;

        -- Copy data from old column names if new ones are empty
        UPDATE teams SET team_name_cn = name_cn WHERE team_name_cn IS NULL AND name_cn IS NOT NULL;
        UPDATE teams SET team_name_en = name_en WHERE team_name_en IS NULL AND name_en IS NOT NULL;
        UPDATE teams SET team_code = canonical_name WHERE team_code IS NULL AND canonical_name IS NOT NULL;
    END IF;
END $$;

-- -------------------------------------------------------------------
-- team_aliases: add 08 columns if missing (only if table exists)
-- -------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'team_aliases'
    ) THEN
        ALTER TABLE team_aliases ADD COLUMN IF NOT EXISTS language VARCHAR(16);
        ALTER TABLE team_aliases ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT false;
    END IF;
END $$;

-- -------------------------------------------------------------------
-- match_feature_snapshots: if 02's version exists (has feature_time
-- instead of snapshot_time), migrate to 12's definition
-- -------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'match_feature_snapshots' AND column_name = 'feature_time'
    ) THEN
        -- Rename feature_time → snapshot_time if the 12 column doesn't exist yet
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'match_feature_snapshots' AND column_name = 'snapshot_time'
        ) THEN
            ALTER TABLE match_feature_snapshots RENAME COLUMN feature_time TO snapshot_time;
        END IF;
    END IF;
END $$;

-- -------------------------------------------------------------------
-- match_feature_snapshots migration (only if table exists)
-- -------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'match_feature_snapshots'
    ) THEN

-- Add 12 columns that 02 didn't have (core identification)
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS competition_season_id BIGINT;

-- Team season strength
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_team_market_value NUMERIC(16,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_team_market_value NUMERIC(16,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS team_market_value_diff NUMERIC(16,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS team_market_value_ratio NUMERIC(10,6);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_attack_strength_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_attack_strength_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_defense_strength_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_defense_strength_score NUMERIC(10,4);

-- Lineup
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_lineup_confirmed BOOLEAN;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_lineup_confirmed BOOLEAN;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_starting_11_value NUMERIC(16,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_starting_11_value NUMERIC(16,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS starting_11_value_diff NUMERIC(16,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_lineup_strength_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_lineup_strength_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS lineup_strength_diff NUMERIC(10,4);

-- Absence/injury
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_absence_impact_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_absence_impact_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS absence_impact_diff NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_key_absence_count INT;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_key_absence_count INT;

-- Rotation/schedule
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_rotation_risk_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_rotation_risk_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS rotation_risk_diff NUMERIC(10,4);

-- Rest days (12 splits rest_days_diff into home/away/diff)
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_rest_days INT;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_rest_days INT;
-- rest_days_diff is already in 02 schema, no migration needed

-- Travel/geography
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS stadium_id BIGINT;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_travel_distance_km NUMERIC(10,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS timezone_diff NUMERIC(5,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS altitude_m NUMERIC(10,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_travel_fatigue_score NUMERIC(10,4);

-- Weather
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS temperature_2m NUMERIC(8,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS precipitation NUMERIC(8,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS wind_speed_10m NUMERIC(8,2);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS weather_impact_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS goal_expectation_weather_adjustment NUMERIC(10,6);

-- Motivation
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_motivation_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_motivation_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS motivation_diff NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_must_win BOOLEAN;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_must_win BOOLEAN;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_draw_enough BOOLEAN;
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_draw_enough BOOLEAN;

-- Tournament incentives
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_avoid_strong_opponent_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_avoid_strong_opponent_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS home_tanking_risk_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS away_tanking_risk_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS tournament_incentive_risk_score NUMERIC(10,4);

-- Data quality (12 expands data_quality_score into 3 columns)
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS data_completeness_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS source_confidence_score NUMERIC(10,4);
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS uncertainty_score NUMERIC(10,4);

-- Feature refs
ALTER TABLE match_feature_snapshots ADD COLUMN IF NOT EXISTS raw_feature_refs JSONB;

-- Note: 12 drops the FK on match_id to official_matches and removes home_elo/away_elo/
-- elo_diff/home_recent_form/away_recent_form/home_xg/away_xg/injury_score_diff.
-- These columns are kept in migrated databases for backward compatibility
-- but are no longer populated.

    END IF;
END $$;
