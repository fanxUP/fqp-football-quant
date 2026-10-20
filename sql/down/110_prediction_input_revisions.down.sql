-- Production recovery is application rollback preserving immutable history.
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='15s';
LOCK TABLE official_matches,official_markets,official_odds_snapshots IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE prediction_input_revisions IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT FROM prediction_input_revisions) THEN
        RAISE EXCEPTION 'retained input revisions: roll back application only';
    END IF;
END $$;
DROP TRIGGER IF EXISTS trg_prediction_official_dirty ON official_matches;
DROP TRIGGER IF EXISTS trg_prediction_official_dirty ON official_markets;
DROP TRIGGER IF EXISTS trg_prediction_official_dirty ON official_odds_snapshots;
DROP FUNCTION IF EXISTS notify_prediction_official_update();
DROP TABLE prediction_input_revisions;
COMMIT;
