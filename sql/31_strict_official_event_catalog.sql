-- The event center is a strict Sporttery betting-history surface.
-- League reference fixtures without a ticket-visible Sporttery match code
-- must never be exposed here as official matches.
DROP VIEW IF EXISTS event_match_catalog;
DROP TABLE IF EXISTS official_season_matches;

-- Remove legacy rows that predate the strict official-identity contract,
-- then make that contract impossible to bypass with another writer.
DELETE FROM official_matches
WHERE official_match_code !~ '^周[一二三四五六日][0-9]{3}$'
   OR source_match_id IS NULL
   OR btrim(source_match_id) = '';

ALTER TABLE official_matches
    ALTER COLUMN source_match_id SET NOT NULL;

CREATE VIEW event_match_catalog AS
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
  AND m.raw_json->>'source' IS DISTINCT FROM '500.com';
