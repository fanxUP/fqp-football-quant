-- 50_repair_api_football_seasons.sql
-- API-Football 各赛事必须使用独立赛季键，避免相同年份互相覆盖日期。

WITH desired_seasons(
    competition_code,
    season_code,
    season_name,
    start_date,
    end_date,
    is_current
) AS (
    VALUES
        ('apifootball:103', 'apifootball:103:2026', '2026赛季', DATE '2026-03-01', DATE '2026-11-30', true),
        ('apifootball:244', 'apifootball:244:2026', '2026赛季', DATE '2026-03-01', DATE '2026-11-30', true),
        ('apifootball:113', 'apifootball:113:2026', '2026赛季', DATE '2026-03-01', DATE '2026-11-30', true),
        ('apifootball:292', 'apifootball:292:2026', '2026赛季', DATE '2026-03-01', DATE '2026-11-30', true),
        ('apifootball:1', 'apifootball:1:2026', '2026世界杯', DATE '2026-06-11', DATE '2026-07-19', true)
)
INSERT INTO seasons (season_code, season_name, start_date, end_date, is_current)
SELECT season_code, season_name, start_date, end_date, is_current
FROM desired_seasons
ON CONFLICT (season_code) DO UPDATE SET
    season_name = EXCLUDED.season_name,
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    is_current = EXCLUDED.is_current,
    updated_at = now();

WITH desired_seasons(competition_code, season_code) AS (
    VALUES
        ('apifootball:103', 'apifootball:103:2026'),
        ('apifootball:244', 'apifootball:244:2026'),
        ('apifootball:113', 'apifootball:113:2026'),
        ('apifootball:292', 'apifootball:292:2026'),
        ('apifootball:1', 'apifootball:1:2026')
)
UPDATE competition_seasons AS competition_season
SET season_id = season.id,
    updated_at = now()
FROM competitions AS competition,
     desired_seasons AS desired,
     seasons AS season
WHERE competition_season.competition_id = competition.id
  AND competition.competition_code = desired.competition_code
  AND season.season_code = desired.season_code
  AND competition_season.season_id <> season.id
  AND NOT EXISTS (
      SELECT 1
      FROM competition_seasons AS existing
      WHERE existing.competition_id = competition_season.competition_id
        AND existing.season_id = season.id
  );
