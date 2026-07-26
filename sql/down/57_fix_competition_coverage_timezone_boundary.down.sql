CREATE OR REPLACE VIEW competition_data_coverage AS
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
 AND emc.kickoff_time::date BETWEEN s.start_date AND s.end_date
LEFT JOIN season_standings_snapshots sss ON sss.competition_season_id = cs.id
GROUP BY cs.id, c.competition_name_cn, s.season_code, cs.total_teams
ORDER BY c.competition_name_cn;
