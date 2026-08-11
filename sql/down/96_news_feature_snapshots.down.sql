DROP TABLE IF EXISTS match_news_features;
DROP TABLE IF EXISTS match_news_snapshots;
ALTER TABLE news_events DROP COLUMN IF EXISTS verified_at;
