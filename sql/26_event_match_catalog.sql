-- Read-only catalog for cross-source event browsing.
-- The source column is mandatory so consumers cannot mistake supplemental
-- data for the Sporttery official schedule.
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
WHERE m.raw_json->>'source' IS DISTINCT FROM '500.com'

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
