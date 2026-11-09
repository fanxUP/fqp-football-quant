SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

LOCK TABLE match_feature_snapshots,prematch_prediction_tasks,sporttery_schedule_notices
    IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM prematch_prediction_tasks)
       OR EXISTS (SELECT 1 FROM sporttery_schedule_notices)
       OR EXISTS (
           SELECT 1 FROM match_feature_snapshots
           WHERE home_team_id IS NULL OR away_team_id IS NULL
       ) THEN
        RAISE EXCEPTION 'Schedule receipts, notices or sparse snapshots exist; keep migration 132 when rolling back the app';
    END IF;
END $$;

ALTER TABLE match_feature_snapshots
    ALTER COLUMN home_team_id SET NOT NULL,
    ALTER COLUMN away_team_id SET NOT NULL,
    DROP CONSTRAINT match_feature_snapshots_team_evidence;
DROP TABLE sporttery_schedule_notices;
DROP TABLE prematch_prediction_tasks;
