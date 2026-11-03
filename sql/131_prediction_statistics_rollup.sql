-- Bounded, rebuildable rollups for the dashboard's historical prediction counts.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS prediction_statistics_dirty_matches (
    match_id BIGINT PRIMARY KEY,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_prediction_statistics_dirty_order
    ON prediction_statistics_dirty_matches(changed_at, match_id);

CREATE TABLE IF NOT EXISTS prediction_statistics_match_rollups (
    match_id BIGINT PRIMARY KEY,
    raw_prediction_total BIGINT NOT NULL CHECK (raw_prediction_total >= 0),
    summary_total BIGINT NOT NULL CHECK (summary_total >= 0),
    summary_positive_ev_count BIGINT NOT NULL
        CHECK (summary_positive_ev_count BETWEEN 0 AND summary_total),
    confidence_sum NUMERIC NOT NULL,
    confidence_count BIGINT NOT NULL CHECK (confidence_count >= 0),
    model_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    latest_predict_time TIMESTAMP,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_ids(p_match_ids BIGINT[])
RETURNS VOID LANGUAGE SQL AS $$
    INSERT INTO prediction_statistics_dirty_matches(match_id)
    SELECT DISTINCT match_id
    FROM unnest(p_match_ids) AS ids(match_id)
    WHERE match_id IS NOT NULL
    ON CONFLICT (match_id) DO UPDATE SET changed_at = clock_timestamp()
$$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_prediction_insert()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(
        ARRAY(SELECT DISTINCT match_id FROM new_rows)
    );
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_prediction_update()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
        SELECT match_id FROM old_rows
        UNION
        SELECT match_id FROM new_rows
    ));
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_prediction_delete()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(
        ARRAY(SELECT DISTINCT match_id FROM old_rows)
    );
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_prediction_statistics_prediction_insert ON model_predictions;
CREATE TRIGGER trg_prediction_statistics_prediction_insert
    AFTER INSERT ON model_predictions
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_prediction_insert();
DROP TRIGGER IF EXISTS trg_prediction_statistics_prediction_update ON model_predictions;
CREATE TRIGGER trg_prediction_statistics_prediction_update
    AFTER UPDATE ON model_predictions
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_prediction_update();
DROP TRIGGER IF EXISTS trg_prediction_statistics_prediction_delete ON model_predictions;
CREATE TRIGGER trg_prediction_statistics_prediction_delete
    AFTER DELETE ON model_predictions
    REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_prediction_delete();

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_group_insert()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(
        ARRAY(SELECT DISTINCT match_id FROM new_rows)
    );
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_group_update()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
        SELECT match_id FROM old_rows
        UNION
        SELECT match_id FROM new_rows
    ));
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_group_delete()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(
        ARRAY(SELECT DISTINCT match_id FROM old_rows)
    );
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_prediction_statistics_group_insert ON model_prediction_groups;
CREATE TRIGGER trg_prediction_statistics_group_insert
    AFTER INSERT ON model_prediction_groups
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_group_insert();
DROP TRIGGER IF EXISTS trg_prediction_statistics_group_update ON model_prediction_groups;
CREATE TRIGGER trg_prediction_statistics_group_update
    AFTER UPDATE ON model_prediction_groups
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_group_update();
DROP TRIGGER IF EXISTS trg_prediction_statistics_group_delete ON model_prediction_groups;
CREATE TRIGGER trg_prediction_statistics_group_delete
    AFTER DELETE ON model_prediction_groups
    REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_group_delete();

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_option_insert()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
        SELECT g.match_id FROM new_rows o
        JOIN model_prediction_groups g ON g.id = o.group_id
        UNION
        SELECT p.match_id FROM new_rows o
        JOIN model_predictions p ON p.id = o.prediction_id
    ));
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_option_update()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
        SELECT g.match_id FROM old_rows o
        JOIN model_prediction_groups g ON g.id = o.group_id
        UNION
        SELECT p.match_id FROM old_rows o
        JOIN model_predictions p ON p.id = o.prediction_id
        UNION
        SELECT g.match_id FROM new_rows o
        JOIN model_prediction_groups g ON g.id = o.group_id
        UNION
        SELECT p.match_id FROM new_rows o
        JOIN model_predictions p ON p.id = o.prediction_id
    ));
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_option_delete()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
        SELECT g.match_id FROM old_rows o
        JOIN model_prediction_groups g ON g.id = o.group_id
        UNION
        SELECT p.match_id FROM old_rows o
        JOIN model_predictions p ON p.id = o.prediction_id
    ));
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_prediction_statistics_option_insert ON model_prediction_group_options;
CREATE TRIGGER trg_prediction_statistics_option_insert
    AFTER INSERT ON model_prediction_group_options
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_option_insert();
DROP TRIGGER IF EXISTS trg_prediction_statistics_option_update ON model_prediction_group_options;
CREATE TRIGGER trg_prediction_statistics_option_update
    AFTER UPDATE ON model_prediction_group_options
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_option_update();
DROP TRIGGER IF EXISTS trg_prediction_statistics_option_delete ON model_prediction_group_options;
CREATE TRIGGER trg_prediction_statistics_option_delete
    AFTER DELETE ON model_prediction_group_options
    REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_option_delete();

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_run_change()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.run_status IS DISTINCT FROM NEW.run_status THEN
        PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
            SELECT DISTINCT match_id FROM model_prediction_groups
            WHERE run_id = NEW.id
        ));
    END IF;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_prediction_statistics_run_status ON model_prediction_runs;
CREATE TRIGGER trg_prediction_statistics_run_status
    AFTER UPDATE OF run_status ON model_prediction_runs
    FOR EACH ROW
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_run_change();

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_model_name()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    IF OLD.model_name IS DISTINCT FROM NEW.model_name THEN
        PERFORM mark_prediction_statistics_dirty_ids(ARRAY(
            SELECT match_id FROM model_predictions WHERE model_version_id = NEW.id
            UNION
            SELECT match_id FROM model_prediction_groups WHERE model_version_id = NEW.id
        ));
    END IF;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_prediction_statistics_model_name ON model_versions;
CREATE TRIGGER trg_prediction_statistics_model_name
    AFTER UPDATE OF model_name ON model_versions
    FOR EACH ROW
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_model_name();

CREATE OR REPLACE FUNCTION mark_prediction_statistics_dirty_from_match_change()
RETURNS TRIGGER LANGUAGE PLPGSQL AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM mark_prediction_statistics_dirty_ids(ARRAY[OLD.id]);
    ELSE
        PERFORM mark_prediction_statistics_dirty_ids(ARRAY[NEW.id]);
    END IF;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_prediction_statistics_match_insert ON official_matches;
CREATE TRIGGER trg_prediction_statistics_match_insert
    AFTER INSERT ON official_matches
    FOR EACH ROW
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_match_change();
DROP TRIGGER IF EXISTS trg_prediction_statistics_match_delete ON official_matches;
CREATE TRIGGER trg_prediction_statistics_match_delete
    AFTER DELETE ON official_matches
    FOR EACH ROW
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_match_change();
DROP TRIGGER IF EXISTS trg_prediction_statistics_match_kickoff ON official_matches;
CREATE TRIGGER trg_prediction_statistics_match_kickoff
    AFTER UPDATE OF kickoff_time ON official_matches
    FOR EACH ROW
    WHEN (OLD.kickoff_time IS DISTINCT FROM NEW.kickoff_time)
    EXECUTE FUNCTION mark_prediction_statistics_dirty_from_match_change();

-- Install the source triggers before seeding so concurrent inserts/updates are
-- either captured by a trigger or present in this bounded official-match scan.
INSERT INTO prediction_statistics_dirty_matches(match_id)
SELECT id FROM official_matches
ON CONFLICT (match_id) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqp') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON
            prediction_statistics_dirty_matches,
            prediction_statistics_match_rollups TO fqp';
        EXECUTE 'GRANT EXECUTE ON FUNCTION
            mark_prediction_statistics_dirty_ids(BIGINT[]),
            mark_prediction_statistics_dirty_from_prediction_insert(),
            mark_prediction_statistics_dirty_from_prediction_update(),
            mark_prediction_statistics_dirty_from_prediction_delete(),
            mark_prediction_statistics_dirty_from_group_insert(),
            mark_prediction_statistics_dirty_from_group_update(),
            mark_prediction_statistics_dirty_from_group_delete(),
            mark_prediction_statistics_dirty_from_option_insert(),
            mark_prediction_statistics_dirty_from_option_update(),
            mark_prediction_statistics_dirty_from_option_delete(),
            mark_prediction_statistics_dirty_from_run_change(),
            mark_prediction_statistics_dirty_from_model_name(),
            mark_prediction_statistics_dirty_from_match_change()
            TO fqp';
    END IF;
END $$;

REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_ids(BIGINT[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_prediction_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_prediction_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_prediction_delete() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_group_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_group_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_group_delete() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_option_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_option_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_option_delete() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_run_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_model_name() FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_prediction_statistics_dirty_from_match_change() FROM PUBLIC;

COMMIT;
