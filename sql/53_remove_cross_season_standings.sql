-- The retired collector queried API-SPORTS season 2024 on the free plan but
-- attached those rows to 2026 competition seasons. Remove the contaminated
-- snapshots before feature rebuilding; verified current-season sources remain.
DELETE FROM season_standings_snapshots snapshot
USING competition_seasons competition_season, seasons season
WHERE snapshot.competition_season_id = competition_season.id
  AND competition_season.season_id = season.id
  AND snapshot.source_name = 'api-football'
  AND season.season_code LIKE '%2026%';
