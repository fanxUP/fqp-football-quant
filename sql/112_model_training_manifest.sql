-- P106-05: persist the exact training rows used to create each new Maher model.
-- Existing model versions are intentionally left without a fabricated manifest.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

CREATE TABLE IF NOT EXISTS model_training_manifests (
    model_version_id BIGINT PRIMARY KEY
        REFERENCES model_versions(id) ON DELETE RESTRICT,
    manifest_json JSONB NOT NULL
        CHECK (jsonb_typeof(manifest_json) = 'object'),
    manifest_canonical BYTEA NOT NULL,
    training_manifest_sha256 CHAR(64) NOT NULL
        CHECK (training_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    content_sha256 CHAR(64) NOT NULL
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    included_count INTEGER NOT NULL CHECK (included_count >= 0),
    excluded_count INTEGER NOT NULL CHECK (excluded_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (COALESCE(manifest_json->>'sha256' = training_manifest_sha256, FALSE)),
    CHECK (COALESCE(jsonb_typeof(manifest_json->'included') = 'array', FALSE)),
    CHECK (COALESCE(jsonb_typeof(manifest_json->'excluded') = 'array', FALSE)),
    CHECK (included_count = COALESCE(jsonb_array_length(manifest_json->'included'), -1)),
    CHECK (excluded_count = COALESCE(jsonb_array_length(manifest_json->'excluded'), -1)),
    CHECK (
        encode(pg_catalog.sha256(manifest_canonical), 'hex') = content_sha256
    ),
    CHECK (
        convert_from(manifest_canonical, 'UTF8')::JSONB = manifest_json
    )
);

CREATE OR REPLACE FUNCTION enforce_model_training_manifest_immutable()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE unique_manifest_keys BOOLEAN;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'model training manifests are immutable';
    END IF;
    EXECUTE format(
        'SELECT %I.prediction_manifest_bytes_have_unique_keys($1)',
        TG_TABLE_SCHEMA
    ) INTO unique_manifest_keys USING NEW.manifest_canonical;
    IF NOT unique_manifest_keys THEN
        RAISE EXCEPTION 'training manifest canonical bytes contain duplicate JSON keys';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION enforce_model_training_manifest_immutable() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_model_training_manifest_immutable ON model_training_manifests;
CREATE TRIGGER trg_model_training_manifest_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON model_training_manifests
    FOR EACH ROW EXECUTE FUNCTION enforce_model_training_manifest_immutable();

REVOKE UPDATE, DELETE ON model_training_manifests FROM fqp;
GRANT SELECT, INSERT ON model_training_manifests TO fqp;

COMMIT;
