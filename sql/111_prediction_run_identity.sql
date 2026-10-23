-- P106-03: additive prediction run/group identity. The legacy prediction table
-- remains unchanged; a view publishes complete vectors and isolates legacy rows.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

CREATE TABLE IF NOT EXISTS model_prediction_runs (
    id UUID PRIMARY KEY,
    ai_job_run_id BIGINT UNIQUE REFERENCES ai_job_runs(id),
    run_status VARCHAR(16) NOT NULL CHECK (run_status IN ('running','completed','partial','failed')),
    provenance_status VARCHAR(16) NOT NULL CHECK (provenance_status IN ('complete','incomplete')),
    release_id VARCHAR(128) NOT NULL,
    code_fingerprint JSONB NOT NULL CHECK (jsonb_typeof(code_fingerprint)='object'),
    model_manifest JSONB NOT NULL CHECK (jsonb_typeof(model_manifest)='array'),
    input_manifest JSONB NOT NULL CHECK (jsonb_typeof(input_manifest)='object'),
    run_manifest JSONB NOT NULL CHECK (jsonb_typeof(run_manifest)='object'),
    run_manifest_sha256 CHAR(64) NOT NULL CHECK (run_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    model_manifest_sha256 CHAR(64) NOT NULL CHECK (model_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    input_manifest_sha256 CHAR(64) NOT NULL CHECK (input_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    output_manifest_sha256 CHAR(64) CHECK (output_manifest_sha256 IS NULL OR output_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    output_summary JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(output_summary)='object'),
    output_manifest JSONB CHECK (output_manifest IS NULL OR jsonb_typeof(output_manifest)='object'),
    output_manifest_canonical BYTEA,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((run_status='running' AND finished_at IS NULL)
        OR (run_status<>'running' AND finished_at IS NOT NULL))
);
ALTER TABLE model_prediction_runs
    ADD COLUMN IF NOT EXISTS output_manifest JSONB,
    ADD COLUMN IF NOT EXISTS output_manifest_canonical BYTEA;
CREATE INDEX IF NOT EXISTS idx_model_prediction_runs_status_time
    ON model_prediction_runs(run_status, started_at DESC);

CREATE OR REPLACE FUNCTION prediction_manifest_bytes_have_unique_keys(payload BYTEA)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE STRICT SET search_path=pg_catalog AS $$
WITH RECURSIVE nodes(path, json_value) AS (
    SELECT ARRAY[]::TEXT[], convert_from(payload, 'UTF8')::JSON
    UNION ALL
    SELECT array_append(parent.path, child.path_part), child.json_value
    FROM nodes parent
    CROSS JOIN LATERAL (
        SELECT 'object:' || member.key AS path_part, member.value AS json_value
        FROM json_each(
            CASE WHEN json_typeof(parent.json_value)='object'
                 THEN parent.json_value ELSE '{}'::JSON END
        ) AS member
        UNION ALL
        SELECT 'array:' || element.ordinality::TEXT, element.value
        FROM json_array_elements(
            CASE WHEN json_typeof(parent.json_value)='array'
                 THEN parent.json_value ELSE '[]'::JSON END
        ) WITH ORDINALITY AS element(value, ordinality)
    ) AS child
)
SELECT NOT EXISTS (
    SELECT 1
    FROM nodes parent
    CROSS JOIN LATERAL json_each(
        CASE WHEN json_typeof(parent.json_value)='object'
             THEN parent.json_value ELSE '{}'::JSON END
    ) AS member
    GROUP BY parent.path, member.key
    HAVING count(*) > 1
)
$$;
REVOKE ALL ON FUNCTION prediction_manifest_bytes_have_unique_keys(BYTEA) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION prediction_manifest_bytes_have_unique_keys(BYTEA) TO fqp;

CREATE OR REPLACE FUNCTION enforce_model_prediction_run_lifecycle()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE object_schema TEXT; has_groups BOOLEAN; completed_group_count BIGINT;
        actual_completed_group_count BIGINT;
        actual_group_hashes JSONB; expected_output_manifest JSONB;
        expected_group_count BIGINT; skipped_group_count BIGINT;
        input_skip_count BIGINT; summary_missing_count BIGINT;
        counts_complete BOOLEAN; unique_manifest_keys BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.run_status <> 'running' THEN
            RAISE EXCEPTION 'prediction runs must start in running state';
        END IF;
        IF NEW.output_summary <> '{}'::jsonb OR NEW.output_manifest_sha256 IS NOT NULL
           OR NEW.output_manifest IS NOT NULL OR NEW.output_manifest_canonical IS NOT NULL THEN
            RAISE EXCEPTION 'running prediction runs cannot carry output summaries';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'prediction runs are immutable records';
    END IF;
    IF OLD.run_status <> 'running' THEN
        RAISE EXCEPTION 'terminal prediction runs are immutable';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.ai_job_run_id IS DISTINCT FROM OLD.ai_job_run_id
       OR NEW.release_id IS DISTINCT FROM OLD.release_id
       OR NEW.code_fingerprint IS DISTINCT FROM OLD.code_fingerprint
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'prediction run identity is immutable';
    END IF;
    object_schema := TG_TABLE_SCHEMA;
    EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.model_prediction_groups WHERE run_id=$1)',
        object_schema
    ) INTO has_groups USING OLD.id;
    IF has_groups AND (
        NEW.model_manifest IS DISTINCT FROM OLD.model_manifest
        OR NEW.input_manifest IS DISTINCT FROM OLD.input_manifest
        OR NEW.run_manifest IS DISTINCT FROM OLD.run_manifest
        OR NEW.run_manifest_sha256 IS DISTINCT FROM OLD.run_manifest_sha256
        OR NEW.model_manifest_sha256 IS DISTINCT FROM OLD.model_manifest_sha256
        OR NEW.input_manifest_sha256 IS DISTINCT FROM OLD.input_manifest_sha256
        OR NEW.provenance_status IS DISTINCT FROM OLD.provenance_status
    ) THEN
        RAISE EXCEPTION 'prediction run manifest is immutable after output begins';
    END IF;
    IF NEW.run_status = 'running' THEN
        IF NEW.finished_at IS NOT NULL
           OR NEW.output_manifest_sha256 IS NOT NULL
           OR NEW.output_manifest IS NOT NULL
           OR NEW.output_manifest_canonical IS NOT NULL
           OR NEW.error_message IS NOT NULL
           OR NEW.output_summary <> '{}'::jsonb THEN
            RAISE EXCEPTION 'running prediction runs cannot carry terminal fields';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.finished_at IS NULL OR NEW.output_manifest_sha256 IS NULL
       OR NEW.output_manifest IS NULL OR NEW.output_manifest_canonical IS NULL THEN
        RAISE EXCEPTION 'terminal prediction runs require output manifest and finish time';
    END IF;
    object_schema := TG_TABLE_SCHEMA;
    EXECUTE format('SELECT %I.prediction_manifest_bytes_have_unique_keys($1)', object_schema)
      INTO unique_manifest_keys USING NEW.output_manifest_canonical;
    IF NOT unique_manifest_keys THEN
        RAISE EXCEPTION 'prediction run output manifest contains duplicate JSON object keys';
    END IF;
    counts_complete := COALESCE((NEW.output_summary->>'counts_complete')::BOOLEAN, TRUE);
    IF jsonb_typeof(NEW.output_summary->'completed_groups') IS DISTINCT FROM 'number'
       OR (counts_complete AND
           jsonb_typeof(NEW.output_summary->'input_updates_skipped') IS DISTINCT FROM 'number')
       OR (NOT counts_complete AND
           jsonb_typeof(NEW.output_summary->'input_updates_skipped') IS DISTINCT FROM 'null')
       OR jsonb_typeof(NEW.output_summary->'missing_groups') IS DISTINCT FROM 'array'
       OR COALESCE(NEW.output_summary->>'completion_reason', '') = '' THEN
        RAISE EXCEPTION 'terminal prediction runs require a complete output summary';
    END IF;
    IF (NEW.output_summary->>'completed_groups')::NUMERIC
           <> trunc((NEW.output_summary->>'completed_groups')::NUMERIC)
       OR (counts_complete AND (
           (NEW.output_summary->>'expected_groups')::NUMERIC
               <> trunc((NEW.output_summary->>'expected_groups')::NUMERIC)
           OR (NEW.output_summary->>'skipped_groups')::NUMERIC
               <> trunc((NEW.output_summary->>'skipped_groups')::NUMERIC)
           OR (NEW.output_summary->>'input_updates_skipped')::NUMERIC
               <> trunc((NEW.output_summary->>'input_updates_skipped')::NUMERIC)
       )) THEN
        RAISE EXCEPTION 'prediction output summary counts must be integers';
    END IF;
    completed_group_count := (NEW.output_summary->>'completed_groups')::BIGINT;
    summary_missing_count := jsonb_array_length(NEW.output_summary->'missing_groups');
    IF counts_complete THEN
        IF jsonb_typeof(NEW.output_summary->'expected_groups') IS DISTINCT FROM 'number'
           OR jsonb_typeof(NEW.output_summary->'skipped_groups') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'complete prediction output counts require numeric expected/skipped groups';
        END IF;
        expected_group_count := (NEW.output_summary->>'expected_groups')::BIGINT;
        skipped_group_count := (NEW.output_summary->>'skipped_groups')::BIGINT;
        input_skip_count := (NEW.output_summary->>'input_updates_skipped')::BIGINT;
    ELSE
        IF NEW.run_status IS DISTINCT FROM 'failed'
           OR NEW.output_summary->'expected_groups' IS DISTINCT FROM 'null'::JSONB
           OR NEW.output_summary->'skipped_groups' IS DISTINCT FROM 'null'::JSONB
           OR summary_missing_count <> 0 THEN
            RAISE EXCEPTION 'unknown prediction output counts are allowed only for failed runs';
        END IF;
        expected_group_count := NULL;
        skipped_group_count := NULL;
        input_skip_count := NULL;
    END IF;
    EXECUTE format(
        'SELECT COUNT(*) FROM %I.model_prediction_groups WHERE run_id=$1 AND group_status=''complete''',
        object_schema
    ) INTO actual_completed_group_count USING NEW.id;
    IF completed_group_count < 0
       OR completed_group_count <> actual_completed_group_count
       OR (counts_complete AND (
           expected_group_count < 0 OR skipped_group_count < 0 OR input_skip_count < 0
           OR expected_group_count <> completed_group_count + skipped_group_count
           OR skipped_group_count <> summary_missing_count
       )) THEN
        RAISE EXCEPTION 'prediction run output summary counts are inconsistent';
    END IF;
    EXECUTE format(
        'SELECT COALESCE(jsonb_agg(output_sha256 ORDER BY match_id, model_version_id, play_type, market_variant, id), ''[]''::jsonb) FROM %I.model_prediction_groups WHERE run_id=$1 AND group_status=''complete''',
        object_schema
    ) INTO actual_group_hashes USING NEW.id;
    expected_output_manifest := jsonb_build_object(
        'groups', actual_group_hashes,
        'summary', NEW.output_summary
    );
    IF convert_from(NEW.output_manifest_canonical, 'UTF8')::jsonb
           IS DISTINCT FROM NEW.output_manifest
       OR encode(pg_catalog.sha256(NEW.output_manifest_canonical), 'hex')
           IS DISTINCT FROM NEW.output_manifest_sha256
       OR NEW.output_manifest IS DISTINCT FROM expected_output_manifest THEN
        RAISE EXCEPTION 'prediction run output manifest SHA-256 does not match content';
    END IF;
    IF NEW.run_status = 'completed'
       AND (skipped_group_count > 0 OR input_skip_count > 0) THEN
        RAISE EXCEPTION 'completed prediction run cannot have skipped outputs';
    END IF;
    IF NEW.run_status = 'partial'
       AND skipped_group_count = 0 AND input_skip_count = 0 AND NEW.error_message IS NULL THEN
        RAISE EXCEPTION 'partial prediction run requires a recorded omission or failure';
    END IF;
    IF NEW.model_manifest IS DISTINCT FROM OLD.model_manifest
       OR NEW.input_manifest IS DISTINCT FROM OLD.input_manifest
       OR NEW.run_manifest IS DISTINCT FROM OLD.run_manifest
       OR NEW.run_manifest_sha256 IS DISTINCT FROM OLD.run_manifest_sha256
       OR NEW.model_manifest_sha256 IS DISTINCT FROM OLD.model_manifest_sha256
       OR NEW.input_manifest_sha256 IS DISTINCT FROM OLD.input_manifest_sha256
       OR NEW.provenance_status IS DISTINCT FROM OLD.provenance_status THEN
        RAISE EXCEPTION 'prediction run identity is immutable';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_model_prediction_run_lifecycle() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_immutable_prediction_run ON model_prediction_runs;
CREATE TRIGGER trg_immutable_prediction_run
    BEFORE INSERT OR UPDATE OR DELETE ON model_prediction_runs FOR EACH ROW
    EXECUTE FUNCTION enforce_model_prediction_run_lifecycle();

CREATE TABLE IF NOT EXISTS model_prediction_groups (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES model_prediction_runs(id),
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    model_version_id BIGINT NOT NULL REFERENCES model_versions(id),
    play_type VARCHAR(32) NOT NULL,
    market_variant VARCHAR(64) NOT NULL DEFAULT '',
    predict_time TIMESTAMP NOT NULL,
    expected_options JSONB NOT NULL CHECK (
        jsonb_typeof(expected_options)='array' AND jsonb_array_length(expected_options) BETWEEN 1 AND 256
    ),
    probability_vector JSONB NOT NULL CHECK (jsonb_typeof(probability_vector)='object'),
    score_matrix JSONB CHECK (score_matrix IS NULL OR jsonb_typeof(score_matrix)='object'),
    odds_snapshot_ids JSONB NOT NULL CHECK (jsonb_typeof(odds_snapshot_ids)='object'),
    odds_snapshot_times JSONB NOT NULL CHECK (jsonb_typeof(odds_snapshot_times)='object'),
    feature_snapshot_id BIGINT,
    input_fence JSONB CHECK (input_fence IS NULL OR jsonb_typeof(input_fence)='object'),
    artifact_identity JSONB CHECK (artifact_identity IS NULL OR jsonb_typeof(artifact_identity)='object'),
    output_manifest JSONB NOT NULL CHECK (jsonb_typeof(output_manifest)='object'),
    output_manifest_canonical BYTEA NOT NULL CHECK (octet_length(output_manifest_canonical) > 0),
    provenance_status VARCHAR(16) NOT NULL CHECK (provenance_status IN ('complete','incomplete')),
    output_sha256 CHAR(64) NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
    group_status VARCHAR(16) NOT NULL CHECK (group_status IN ('building','complete')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    UNIQUE (run_id, match_id, model_version_id, play_type, market_variant),
    CHECK ((group_status='building' AND completed_at IS NULL)
        OR (group_status='complete' AND completed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_model_prediction_groups_latest
    ON model_prediction_groups(match_id, model_version_id, play_type, predict_time DESC, created_at DESC)
    WHERE group_status='complete';
CREATE INDEX IF NOT EXISTS idx_model_prediction_groups_run
    ON model_prediction_groups(run_id, group_status, match_id);

CREATE TABLE IF NOT EXISTS model_prediction_group_options (
    group_id UUID NOT NULL REFERENCES model_prediction_groups(id),
    option_code VARCHAR(64) NOT NULL,
    prediction_id BIGINT NOT NULL UNIQUE REFERENCES model_predictions(id),
    ordinal SMALLINT NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (group_id, option_code),
    UNIQUE (group_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_model_prediction_group_options_prediction
    ON model_prediction_group_options(prediction_id);

CREATE OR REPLACE FUNCTION validate_model_prediction_group_options()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE expected TEXT[]; actual TEXT[]; object_schema TEXT;
        parent_status TEXT; invalid_prediction BOOLEAN; actual_vector JSONB;
        parent_provenance_status TEXT; parent_model_manifest JSONB;
        model_identity_count BIGINT; matching_identity_count BIGINT;
        output_option_count BIGINT; output_options TEXT[];
        unique_manifest_keys BOOLEAN;
BEGIN
    IF NEW.group_status <> 'complete' OR OLD.group_status = 'complete' THEN
        RETURN NEW;
    END IF;
    object_schema := TG_TABLE_SCHEMA;
    EXECUTE format('SELECT %I.prediction_manifest_bytes_have_unique_keys($1)', object_schema)
      INTO unique_manifest_keys USING NEW.output_manifest_canonical;
    IF NOT unique_manifest_keys THEN
        RAISE EXCEPTION 'prediction output manifest contains duplicate JSON object keys';
    END IF;
    IF convert_from(NEW.output_manifest_canonical, 'UTF8')::jsonb
           IS DISTINCT FROM NEW.output_manifest
       OR encode(pg_catalog.sha256(NEW.output_manifest_canonical), 'hex')
           IS DISTINCT FROM NEW.output_sha256 THEN
        RAISE EXCEPTION 'prediction output manifest SHA-256 does not match content';
    END IF;
    IF NEW.output_manifest->'match_id' IS DISTINCT FROM to_jsonb(NEW.match_id)
       OR NEW.output_manifest->'model_version_id' IS DISTINCT FROM to_jsonb(NEW.model_version_id)
       OR NEW.output_manifest->'play_type' IS DISTINCT FROM to_jsonb(NEW.play_type)
       OR NEW.output_manifest->'market_variant' IS DISTINCT FROM to_jsonb(NEW.market_variant)
       OR NEW.output_manifest->'predict_time' IS DISTINCT FROM to_jsonb(NEW.predict_time)
       OR NEW.output_manifest->'expected_options' IS DISTINCT FROM NEW.expected_options
       OR NEW.output_manifest->'probability_vector' IS DISTINCT FROM NEW.probability_vector
       OR NEW.output_manifest->'odds_snapshot_ids' IS DISTINCT FROM NEW.odds_snapshot_ids
       OR NEW.output_manifest->'odds_snapshot_times' IS DISTINCT FROM NEW.odds_snapshot_times
       OR COALESCE(NEW.output_manifest->'score_matrix', 'null'::jsonb)
           IS DISTINCT FROM COALESCE(to_jsonb(NEW.score_matrix), 'null'::jsonb)
       OR COALESCE(NEW.output_manifest->'input_fence', 'null'::jsonb)
           IS DISTINCT FROM COALESCE(NEW.input_fence, 'null'::jsonb)
       OR COALESCE(NEW.output_manifest->'artifact_identity', 'null'::jsonb)
           IS DISTINCT FROM COALESCE(NEW.artifact_identity, 'null'::jsonb)
       OR COALESCE(NEW.output_manifest->'feature_snapshot_id', 'null'::jsonb)
           IS DISTINCT FROM COALESCE(to_jsonb(NEW.feature_snapshot_id), 'null'::jsonb) THEN
        RAISE EXCEPTION 'prediction output manifest does not match its group';
    END IF;
    SELECT ARRAY(SELECT jsonb_array_elements_text(NEW.expected_options) ORDER BY 1)
      INTO expected;
    SELECT jsonb_array_length(NEW.output_manifest->'prediction_outputs')
      INTO output_option_count;
    SELECT ARRAY(
        SELECT option.item->>'option_code'
        FROM jsonb_array_elements(NEW.output_manifest->'prediction_outputs') AS option(item)
        ORDER BY 1
    ) INTO output_options;
    IF output_option_count IS DISTINCT FROM jsonb_array_length(NEW.expected_options)
       OR expected IS DISTINCT FROM output_options THEN
        RAISE EXCEPTION 'prediction output manifest option count is incomplete';
    END IF;
    EXECUTE format(
        'SELECT COALESCE(array_agg(option_code ORDER BY option_code), ARRAY[]::TEXT[]) FROM %I.model_prediction_group_options WHERE group_id=$1',
        object_schema
    ) INTO actual USING NEW.id;
    IF expected IS DISTINCT FROM actual THEN
        RAISE EXCEPTION 'prediction group option set does not match expected options';
    END IF;
    EXECUTE format(
        'SELECT run_status, provenance_status, model_manifest FROM %I.model_prediction_runs WHERE id=$1 FOR UPDATE',
        object_schema
    ) INTO parent_status, parent_provenance_status, parent_model_manifest USING NEW.run_id;
    IF parent_status IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'prediction run must be running while its group is published';
    END IF;
    IF NEW.provenance_status = 'complete' THEN
        IF parent_provenance_status IS DISTINCT FROM 'complete'
           OR NEW.artifact_identity IS NULL
           OR NEW.artifact_identity->>'provenance_status' IS DISTINCT FROM 'complete' THEN
            RAISE EXCEPTION 'complete prediction artifact is missing parent run provenance';
        END IF;
        SELECT COUNT(*), COUNT(*) FILTER (WHERE model.item = NEW.artifact_identity)
          INTO model_identity_count, matching_identity_count
        FROM jsonb_array_elements(parent_model_manifest) AS model(item)
        WHERE model.item->'model_version_id' = to_jsonb(NEW.model_version_id);
        IF model_identity_count <> 1 OR matching_identity_count <> 1 THEN
            RAISE EXCEPTION 'prediction artifact identity does not match parent run manifest';
        END IF;
    END IF;
    EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.model_prediction_group_options option_map JOIN %I.model_predictions mp ON mp.id=option_map.prediction_id WHERE option_map.group_id=$1 AND (option_map.option_code<>mp.option_code OR mp.match_id<>$2 OR mp.model_version_id<>$3 OR mp.play_type<>$4 OR mp.predict_time<>$5))',
        object_schema, object_schema
    ) INTO invalid_prediction USING NEW.id, NEW.match_id, NEW.model_version_id,
                                      NEW.play_type, NEW.predict_time;
    IF invalid_prediction THEN
        RAISE EXCEPTION 'prediction rows do not match their output group';
    END IF;
    EXECUTE format(
        'SELECT COALESCE(jsonb_object_agg(option_map.option_code, mp.model_probability), ''{}''::jsonb) FROM %I.model_prediction_group_options option_map JOIN %I.model_predictions mp ON mp.id=option_map.prediction_id WHERE option_map.group_id=$1',
        object_schema, object_schema
    ) INTO actual_vector USING NEW.id;
    IF NEW.probability_vector IS DISTINCT FROM actual_vector THEN
        RAISE EXCEPTION 'prediction group vector does not match mapped prediction rows';
    END IF;
    EXECUTE format(
        'SELECT EXISTS (
             SELECT 1
             FROM jsonb_array_elements($1->''prediction_outputs'') AS output(item)
             LEFT JOIN %I.model_prediction_group_options option_map
               ON option_map.group_id=$2 AND option_map.option_code=output.item->>''option_code''
             LEFT JOIN %I.model_predictions mp ON mp.id=option_map.prediction_id
             WHERE mp.id IS NULL
                OR output.item IS DISTINCT FROM (to_jsonb(mp) - ARRAY[''id'', ''created_at'']::TEXT[])
         )',
        object_schema, object_schema
    ) INTO invalid_prediction USING NEW.output_manifest, NEW.id;
    IF invalid_prediction THEN
        RAISE EXCEPTION 'prediction output manifest options do not match stored rows';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION validate_model_prediction_group_options() FROM PUBLIC;
CREATE OR REPLACE FUNCTION reject_published_prediction_group_mutation()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE current_status TEXT; object_schema TEXT; target_group_id UUID;
        locked_prediction_id BIGINT;
BEGIN
    object_schema := TG_TABLE_SCHEMA;
    IF TG_TABLE_NAME='model_prediction_groups' THEN
        IF TG_OP='INSERT' THEN RETURN NEW; END IF;
        current_status=OLD.group_status;
    ELSE
        IF TG_OP='UPDATE' THEN
            RAISE EXCEPTION 'prediction group option mappings are immutable';
        END IF;
        IF TG_TABLE_NAME='model_prediction_group_options' AND TG_OP='INSERT' THEN
            EXECUTE format(
                'SELECT id FROM %I.model_predictions WHERE id=$1 FOR UPDATE',
                object_schema
            ) INTO locked_prediction_id USING NEW.prediction_id;
        END IF;
        target_group_id := CASE WHEN TG_OP='INSERT' THEN NEW.group_id ELSE OLD.group_id END;
        EXECUTE format(
            'SELECT group_status FROM %I.model_prediction_groups WHERE id=$1 FOR UPDATE',
            object_schema
        )
          INTO current_status USING target_group_id;
    END IF;
    IF current_status='complete' THEN
        RAISE EXCEPTION 'completed prediction groups are immutable';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION reject_published_prediction_group_mutation() FROM PUBLIC;
CREATE OR REPLACE FUNCTION enforce_prediction_group_starts_building()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE object_schema TEXT; parent_status TEXT;
BEGIN
    IF TG_OP = 'INSERT' AND NEW.group_status <> 'building' THEN
        RAISE EXCEPTION 'prediction groups must start in building state';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.group_status = 'complete' THEN
        RAISE EXCEPTION 'completed prediction groups are immutable';
    END IF;
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(NEW) - 'group_status' - 'completed_at')
           IS DISTINCT FROM (to_jsonb(OLD) - 'group_status' - 'completed_at') THEN
        RAISE EXCEPTION 'prediction group identity is immutable while building';
    END IF;
    object_schema := TG_TABLE_SCHEMA;
    EXECUTE format(
        'SELECT run_status FROM %I.model_prediction_runs WHERE id=$1 FOR UPDATE',
        object_schema
    ) INTO parent_status USING NEW.run_id;
    IF parent_status IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'prediction run must remain running while its group is built';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_prediction_group_starts_building() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_validate_prediction_group_options ON model_prediction_groups;
CREATE CONSTRAINT TRIGGER trg_validate_prediction_group_options
    AFTER UPDATE OF group_status ON model_prediction_groups
    DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW
    EXECUTE FUNCTION validate_model_prediction_group_options();
DROP TRIGGER IF EXISTS trg_prediction_group_must_start_building ON model_prediction_groups;
CREATE TRIGGER trg_prediction_group_must_start_building
    BEFORE INSERT OR UPDATE ON model_prediction_groups FOR EACH ROW
    EXECUTE FUNCTION enforce_prediction_group_starts_building();
DROP TRIGGER IF EXISTS trg_immutable_completed_prediction_group ON model_prediction_groups;
CREATE TRIGGER trg_immutable_completed_prediction_group
    BEFORE UPDATE OR DELETE ON model_prediction_groups FOR EACH ROW
    EXECUTE FUNCTION reject_published_prediction_group_mutation();
DROP TRIGGER IF EXISTS trg_immutable_completed_prediction_group_option ON model_prediction_group_options;
CREATE TRIGGER trg_immutable_completed_prediction_group_option
    BEFORE INSERT OR UPDATE OR DELETE ON model_prediction_group_options FOR EACH ROW
    EXECUTE FUNCTION reject_published_prediction_group_mutation();

CREATE OR REPLACE FUNCTION reject_mapped_prediction_mutation()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE object_schema TEXT; is_mapped BOOLEAN;
BEGIN
    object_schema := TG_TABLE_SCHEMA;
    EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.model_prediction_group_options WHERE prediction_id=$1)',
        object_schema
    ) INTO is_mapped USING OLD.id;
    IF is_mapped THEN
        RAISE EXCEPTION 'run-aware prediction rows are immutable';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION reject_mapped_prediction_mutation() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_immutable_run_aware_prediction ON model_predictions;
CREATE TRIGGER trg_immutable_run_aware_prediction
    BEFORE UPDATE OR DELETE ON model_predictions FOR EACH ROW
    EXECUTE FUNCTION reject_mapped_prediction_mutation();

CREATE OR REPLACE VIEW model_prediction_latest_rows AS
WITH latest_groups AS (
    SELECT DISTINCT ON (g.match_id, mv.model_name, g.play_type)
           g.id AS group_id, g.run_id, g.match_id, mv.model_name, g.play_type
    FROM model_prediction_groups g
    JOIN model_prediction_runs r ON r.id=g.run_id
    JOIN model_versions mv ON mv.id=g.model_version_id
    WHERE g.group_status='complete' AND r.run_status IN ('completed','partial')
    ORDER BY g.match_id, mv.model_name, g.play_type,
             g.predict_time DESC, g.created_at DESC, g.id DESC
), grouped_rows AS (
    SELECT mp.id, mp.match_id, mp.model_version_id, mp.odds_snapshot_id,
           mp.feature_snapshot_id, mp.predict_time, mp.play_type, mp.option_code,
           mp.raw_model_probability, mp.model_probability, mp.market_probability,
           mp.probability_lower_bound, mp.probability_upper_bound, mp.uncertainty_score,
           mp.adjusted_probability, mp.fair_odds, mp.ev, mp.confidence_score, mp.risk_score,
           mp.break_even_probability, mp.market_edge, mp.breakeven_edge,
           mp.validation_status, mp.validation_errors, mp.calculation_version,
           mp.uncertainty_reason, mp.created_at,
           g.run_id AS prediction_run_id,
           g.id AS prediction_group_id,
           g.provenance_status AS group_provenance_status
    FROM latest_groups latest
    JOIN model_prediction_groups g ON g.id=latest.group_id
    JOIN model_prediction_group_options option_map ON option_map.group_id=g.id
    JOIN model_predictions mp ON mp.id=option_map.prediction_id
), legacy_ranked AS (
    SELECT mp.*, NULL::UUID AS prediction_run_id,
           NULL::UUID AS prediction_group_id,
           'incomplete'::VARCHAR(16) AS group_provenance_status,
           ROW_NUMBER() OVER (
               PARTITION BY mp.match_id, mv.model_name, mp.play_type, mp.option_code
               ORDER BY mp.predict_time DESC, mp.id DESC
           ) AS legacy_rank
    FROM model_predictions mp
    JOIN model_versions mv ON mv.id=mp.model_version_id
    WHERE NOT EXISTS (
        SELECT 1 FROM model_prediction_group_options mapped
        WHERE mapped.prediction_id=mp.id
    )
      AND NOT EXISTS (
        SELECT 1 FROM model_prediction_groups g
        JOIN model_prediction_runs r ON r.id=g.run_id
        JOIN model_versions grouped_mv ON grouped_mv.id=g.model_version_id
        WHERE g.match_id=mp.match_id AND grouped_mv.model_name=mv.model_name
          AND g.play_type=mp.play_type AND g.group_status='complete'
          AND r.run_status IN ('completed','partial')
      )
), legacy_rows AS (
    SELECT id, match_id, model_version_id, odds_snapshot_id, feature_snapshot_id,
           predict_time, play_type, option_code, raw_model_probability,
           model_probability, market_probability, probability_lower_bound,
           probability_upper_bound, uncertainty_score, adjusted_probability,
           fair_odds, ev, confidence_score, risk_score, break_even_probability,
           market_edge, breakeven_edge, validation_status, validation_errors,
           calculation_version, uncertainty_reason, created_at, prediction_run_id,
           prediction_group_id, group_provenance_status
    FROM legacy_ranked WHERE legacy_rank=1
)
SELECT * FROM grouped_rows
UNION ALL
SELECT legacy_rows.id, legacy_rows.match_id, legacy_rows.model_version_id,
       legacy_rows.odds_snapshot_id, legacy_rows.feature_snapshot_id,
       legacy_rows.predict_time, legacy_rows.play_type, legacy_rows.option_code,
       legacy_rows.raw_model_probability, legacy_rows.model_probability,
       legacy_rows.market_probability, legacy_rows.probability_lower_bound,
       legacy_rows.probability_upper_bound, legacy_rows.uncertainty_score,
       legacy_rows.adjusted_probability, legacy_rows.fair_odds, legacy_rows.ev,
       legacy_rows.confidence_score, legacy_rows.risk_score,
       legacy_rows.break_even_probability, legacy_rows.market_edge,
       legacy_rows.breakeven_edge, legacy_rows.validation_status,
       legacy_rows.validation_errors, legacy_rows.calculation_version,
       legacy_rows.uncertainty_reason, legacy_rows.created_at,
       legacy_rows.prediction_run_id, legacy_rows.prediction_group_id,
       legacy_rows.group_provenance_status
FROM legacy_rows;

GRANT SELECT, INSERT, UPDATE ON model_prediction_runs TO fqp;
GRANT SELECT, INSERT, UPDATE ON model_prediction_groups TO fqp;
GRANT SELECT, INSERT ON model_prediction_group_options TO fqp;
GRANT SELECT ON model_prediction_latest_rows TO fqp;
COMMIT;
