-- Never remove retained input publications as part of application rollback.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
LOCK TABLE feature_batches IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM feature_batches LIMIT 1) THEN
        RAISE EXCEPTION 'retained feature batches: roll back application only';
    END IF;
END $$;
DROP TABLE feature_batches;
COMMIT;
