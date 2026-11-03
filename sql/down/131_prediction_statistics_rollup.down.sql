BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

DROP TRIGGER IF EXISTS trg_prediction_statistics_match_kickoff ON official_matches;
DROP TRIGGER IF EXISTS trg_prediction_statistics_match_delete ON official_matches;
DROP TRIGGER IF EXISTS trg_prediction_statistics_match_insert ON official_matches;
DROP TRIGGER IF EXISTS trg_prediction_statistics_model_name ON model_versions;
DROP TRIGGER IF EXISTS trg_prediction_statistics_run_status ON model_prediction_runs;
DROP TRIGGER IF EXISTS trg_prediction_statistics_option_delete ON model_prediction_group_options;
DROP TRIGGER IF EXISTS trg_prediction_statistics_option_update ON model_prediction_group_options;
DROP TRIGGER IF EXISTS trg_prediction_statistics_option_insert ON model_prediction_group_options;
DROP TRIGGER IF EXISTS trg_prediction_statistics_group_delete ON model_prediction_groups;
DROP TRIGGER IF EXISTS trg_prediction_statistics_group_update ON model_prediction_groups;
DROP TRIGGER IF EXISTS trg_prediction_statistics_group_insert ON model_prediction_groups;
DROP TRIGGER IF EXISTS trg_prediction_statistics_prediction_delete ON model_predictions;
DROP TRIGGER IF EXISTS trg_prediction_statistics_prediction_update ON model_predictions;
DROP TRIGGER IF EXISTS trg_prediction_statistics_prediction_insert ON model_predictions;

DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_match_change();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_model_name();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_run_change();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_option_delete();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_option_update();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_option_insert();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_group_delete();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_group_update();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_group_insert();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_prediction_delete();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_prediction_update();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_from_prediction_insert();
DROP FUNCTION IF EXISTS mark_prediction_statistics_dirty_ids(BIGINT[]);

DROP TABLE IF EXISTS prediction_statistics_match_rollups;
DROP TABLE IF EXISTS prediction_statistics_dirty_matches;

DO $$
BEGIN
    IF to_regclass('local_schema_migrations') IS NOT NULL THEN
        DELETE FROM local_schema_migrations
        WHERE filename = '131_prediction_statistics_rollup.sql';
    END IF;
END $$;

COMMIT;
