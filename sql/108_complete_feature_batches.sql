-- P104: complete is inserted together with all declared values/references.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
CREATE TABLE IF NOT EXISTS feature_batches (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    cutoff_id UUID NOT NULL,
    cutoff_as_of TIMESTAMPTZ NOT NULL,
    builder_version VARCHAR(64) NOT NULL,
    feature_schema_version VARCHAR(64) NOT NULL,
    required_fields JSONB NOT NULL CHECK (
        jsonb_typeof(required_fields)='array' AND jsonb_array_length(required_fields) BETWEEN 1 AND 64
    ),
    fields_hash CHAR(64) NOT NULL,
    features JSON NOT NULL CHECK (json_typeof(features)='object' AND octet_length(features::text)<=524288),
    status VARCHAR(16) NOT NULL CHECK (status::TEXT IN ('running','partial','complete')),
    content_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (cutoff_id,cutoff_as_of) REFERENCES observation_cutoffs(id,as_of)
);
CREATE INDEX IF NOT EXISTS idx_feature_batch_latest ON feature_batches (
    match_id,builder_version,feature_schema_version,fields_hash,cutoff_as_of DESC,id DESC
);
CREATE INDEX IF NOT EXISTS idx_feature_batch_complete ON feature_batches (
    match_id,builder_version,feature_schema_version,fields_hash,cutoff_as_of DESC,id DESC
) WHERE status='complete';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE
        tgrelid='feature_batches'::regclass AND tgname='observation_immutable') THEN
        CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON feature_batches FOR EACH STATEMENT EXECUTE FUNCTION reject_observation_mutation();
    END IF;
END $$;
COMMIT;
