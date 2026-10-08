-- Rebuildable invalidation queue. No FK: deletion cascades must be able to
-- record old prediction match IDs even after the parent match is removed.
CREATE TABLE IF NOT EXISTS model_performance_dirty_matches (
    match_id BIGINT PRIMARY KEY,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION mark_model_performance_dirty()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        INSERT INTO model_performance_dirty_matches(match_id) VALUES (OLD.match_id)
        ON CONFLICT (match_id) DO UPDATE SET changed_at = clock_timestamp();
    END IF;
    IF TG_OP <> 'DELETE' AND (TG_OP = 'INSERT' OR NEW.match_id IS DISTINCT FROM OLD.match_id) THEN
        INSERT INTO model_performance_dirty_matches(match_id) VALUES (NEW.match_id)
        ON CONFLICT (match_id) DO UPDATE SET changed_at = clock_timestamp();
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER trg_model_performance_prediction_dirty
AFTER INSERT OR UPDATE OR DELETE ON model_predictions
FOR EACH ROW EXECUTE FUNCTION mark_model_performance_dirty();
