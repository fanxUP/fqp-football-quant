-- Official Sporttery league-season fixture archive.
-- A fixture can be official even when it was never offered for betting. Such
-- rows stay here and never receive an invented official_match_code.
CREATE TABLE IF NOT EXISTS official_season_matches (
    id BIGSERIAL PRIMARY KEY,
    uniform_match_id BIGINT NOT NULL,
    gm_match_id VARCHAR(64),
    official_match_id BIGINT REFERENCES official_matches(id) ON DELETE SET NULL,
    uniform_league_id BIGINT NOT NULL,
    season_id BIGINT NOT NULL,
    season_name VARCHAR(64) NOT NULL,
    season_start_date DATE NOT NULL,
    season_end_date DATE NOT NULL,
    selection_reason VARCHAR(32) NOT NULL,
    competition_season_id BIGINT REFERENCES competition_seasons(id),
    uniform_home_team_id BIGINT,
    uniform_away_team_id BIGINT,
    home_team_id BIGINT REFERENCES teams(id),
    away_team_id BIGINT REFERENCES teams(id),
    league_name VARCHAR(128) NOT NULL,
    home_team_name VARCHAR(128) NOT NULL,
    away_team_name VARCHAR(128) NOT NULL,
    kickoff_time TIMESTAMP NOT NULL,
    round_name VARCHAR(64),
    phase_name VARCHAR(128),
    match_status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
    half_home_goals INT,
    half_away_goals INT,
    full_home_goals INT,
    full_away_goals INT,
    source_name VARCHAR(64) NOT NULL DEFAULT 'sporttery',
    source_url TEXT NOT NULL,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (uniform_league_id, season_id, uniform_match_id),
    CONSTRAINT official_season_matches_source
        CHECK (source_name = 'sporttery'),
    CONSTRAINT official_season_matches_nonnegative_score
        CHECK (
            (half_home_goals IS NULL OR half_home_goals >= 0)
            AND (half_away_goals IS NULL OR half_away_goals >= 0)
            AND (full_home_goals IS NULL OR full_home_goals >= 0)
            AND (full_away_goals IS NULL OR full_away_goals >= 0)
        )
);

CREATE INDEX IF NOT EXISTS idx_official_season_matches_league_time
    ON official_season_matches (league_name, kickoff_time);
CREATE INDEX IF NOT EXISTS idx_official_season_matches_season
    ON official_season_matches (uniform_league_id, season_id, kickoff_time);
CREATE INDEX IF NOT EXISTS idx_official_season_matches_gm_match
    ON official_season_matches (gm_match_id)
    WHERE gm_match_id IS NOT NULL;

-- Rebuild the read-only event catalog with a distinct source label for
-- official league fixtures that do not have a Sporttery betting identity.
CREATE OR REPLACE VIEW event_match_catalog AS
SELECT
    'official'::VARCHAR(16) AS source,
    m.id AS source_row_id,
    m.official_match_code AS source_match_code,
    NULL::BIGINT AS supplemental_id,
    NULL::BIGINT AS competition_season_id,
    NULL::BIGINT AS home_team_id,
    NULL::BIGINT AS away_team_id,
    m.league_name,
    m.home_team_name,
    m.away_team_name,
    m.kickoff_time,
    m.match_status,
    r.full_home_goals,
    r.full_away_goals,
    m.source_url
FROM official_matches m
LEFT JOIN official_results r ON r.match_id = m.id
WHERE m.official_match_code ~ '^周[一二三四五六日][0-9]{3}$'
  AND m.source_match_id IS NOT NULL
  AND m.raw_json->>'source' IS DISTINCT FROM '500.com'

UNION ALL

SELECT
    'official_season'::VARCHAR(16) AS source,
    osm.id AS source_row_id,
    NULL::VARCHAR(32) AS source_match_code,
    NULL::BIGINT AS supplemental_id,
    osm.competition_season_id,
    osm.home_team_id,
    osm.away_team_id,
    osm.league_name,
    osm.home_team_name,
    osm.away_team_name,
    osm.kickoff_time,
    osm.match_status,
    osm.full_home_goals,
    osm.full_away_goals,
    osm.source_url
FROM official_season_matches osm
WHERE osm.official_match_id IS NULL

UNION ALL

SELECT
    'supplemental'::VARCHAR(16) AS source,
    sm.id AS source_row_id,
    sm.source_match_id AS source_match_code,
    sm.id AS supplemental_id,
    sm.competition_season_id,
    sm.home_team_id,
    sm.away_team_id,
    sm.league_name,
    sm.home_team_name,
    sm.away_team_name,
    sm.kickoff_time,
    sm.match_status,
    sm.full_home_goals,
    sm.full_away_goals,
    sm.source_url
FROM supplemental_matches sm;
