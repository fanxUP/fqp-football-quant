BEGIN;

DROP TABLE IF EXISTS feature_promotion_audits;
DROP TABLE IF EXISTS hypothesis_validation_runs;
DROP TABLE IF EXISTS research_hypotheses;
DROP TABLE IF EXISTS player_knowledge_profiles;
DROP TABLE IF EXISTS team_knowledge_profiles;
DROP TABLE IF EXISTS league_knowledge_profiles;
DROP TABLE IF EXISTS upset_report_metrics;
DROP TABLE IF EXISTS upset_reviews;
DROP TABLE IF EXISTS upset_factor_evidence;
DROP TABLE IF EXISTS upset_market_signals;
DROP TABLE IF EXISTS upset_events;
DROP TABLE IF EXISTS upset_rule_versions;

DELETE FROM local_schema_migrations
WHERE filename = '48_upset_intelligence_schema.sql';

COMMIT;
