-- Preserve notification positions and receipts during application rollback.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
LOCK TABLE observation_checks IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE prediction_input_dirty_matches,prediction_input_consumers,
    prediction_input_consumptions IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT FROM prediction_input_dirty_matches)
       OR EXISTS (SELECT FROM prediction_input_consumers)
       OR EXISTS (SELECT FROM prediction_input_consumptions) THEN
        RAISE EXCEPTION 'retained input updates: roll back application only';
    END IF;
END $$;
DROP TRIGGER trg_prediction_input_dirty ON observation_checks;
DROP FUNCTION notify_prediction_input_update();
DROP TABLE prediction_input_consumptions;
DROP TABLE prediction_input_consumers;
DROP TABLE prediction_input_dirty_matches;
COMMIT;
