-- Remove only rebuildable model-history derivatives; source predictions and
-- official results remain untouched.
DROP TABLE IF EXISTS model_performance_scored_picks;
DROP TABLE IF EXISTS model_performance_scored_picks_state;
