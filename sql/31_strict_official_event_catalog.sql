-- The event center is a strict Sporttery betting-history surface.
-- League reference fixtures without a ticket-visible Sporttery match code
-- must never be exposed here as official matches.
DROP VIEW IF EXISTS competition_data_coverage;
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

CREATE VIEW competition_data_coverage AS
SELECT
    cs.id AS competition_season_id,
    c.competition_name_cn AS competition_name,
    s.season_code,
    cs.total_teams,
    COUNT(DISTINCT emc.source_row_id) AS official_match_count,
    0::BIGINT AS supplemental_match_count,
    COUNT(DISTINCT CASE WHEN sss.source_name <> '500com_derived' THEN sss.id END)
        AS official_standings_snapshot_count,
    COUNT(DISTINCT CASE WHEN sss.source_name = '500com_derived' THEN sss.id END)
        AS supplemental_standings_snapshot_count,
    MAX(CASE WHEN sss.source_name <> '500com_derived' THEN sss.snapshot_time END)
        AS latest_official_standings_at,
    MAX(CASE WHEN sss.source_name = '500com_derived' THEN sss.snapshot_time END)
        AS latest_supplemental_standings_at,
    0::BIGINT AS mapped_supplemental_match_count,
    0::BIGINT AS unmapped_supplemental_match_count
FROM competition_seasons cs
JOIN competitions c ON c.id = cs.competition_id
JOIN seasons s ON s.id = cs.season_id
LEFT JOIN event_match_catalog emc
  ON emc.league_name = c.competition_name_cn
 AND EXTRACT(YEAR FROM emc.kickoff_time) = s.season_code::int
LEFT JOIN season_standings_snapshots sss ON sss.competition_season_id = cs.id
GROUP BY cs.id, c.competition_name_cn, s.season_code, cs.total_teams
ORDER BY c.competition_name_cn;
