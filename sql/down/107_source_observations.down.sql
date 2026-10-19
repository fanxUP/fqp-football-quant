-- Never erase acquired history as part of application rollback.
-- Own the migration transaction; do not run inside a business transaction.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
-- Serialize the emptiness check with all writers; never check then race a DROP.
LOCK TABLE observation_streams, observation_revisions, observation_checks, observation_cutoffs IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM observation_cutoffs LIMIT 1)
       OR EXISTS (SELECT 1 FROM observation_streams LIMIT 1)
       OR EXISTS (SELECT 1 FROM observation_revisions LIMIT 1)
       OR EXISTS (SELECT 1 FROM observation_checks LIMIT 1) THEN
        RAISE EXCEPTION 'retained observations: roll back application only; export/review required';
    END IF;
END $$;
DROP TABLE observation_cutoffs;
DROP TABLE observation_checks;
DROP TABLE observation_revisions;
DROP TABLE observation_streams;
DROP FUNCTION reject_observation_mutation();
COMMIT;
