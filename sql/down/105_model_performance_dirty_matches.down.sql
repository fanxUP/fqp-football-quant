DROP TRIGGER IF EXISTS trg_model_performance_prediction_dirty ON model_predictions;
DROP FUNCTION IF EXISTS mark_model_performance_dirty();
DROP TABLE IF EXISTS model_performance_dirty_matches;
