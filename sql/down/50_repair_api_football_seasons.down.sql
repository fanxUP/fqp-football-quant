-- 回滚 API-Football 独立赛季关联；保留新增赛季记录，避免破坏引用。

INSERT INTO seasons (season_code, season_name, start_date, end_date, is_current)
VALUES ('2026', '2026世界杯', DATE '2026-03-01', DATE '2026-07-19', true)
ON CONFLICT (season_code) DO NOTHING;

UPDATE competition_seasons AS competition_season
SET season_id = season.id,
    updated_at = now()
FROM competitions AS competition,
     seasons AS season
WHERE competition_season.competition_id = competition.id
  AND competition.competition_code LIKE 'apifootball:%'
  AND season.season_code = '2026'
  AND competition_season.season_id <> season.id
  AND NOT EXISTS (
      SELECT 1
      FROM competition_seasons AS existing
      WHERE existing.competition_id = competition_season.competition_id
        AND existing.season_id = season.id
  );
