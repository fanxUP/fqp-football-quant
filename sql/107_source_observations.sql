-- Additive P104 slice. No historical rows are copied or reinterpreted.
-- Runtime writers use SELECT/INSERT only. Existing identities remain authoritative.
-- Own the migration transaction so psql -f also applies the file atomically.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

CREATE TABLE IF NOT EXISTS observation_streams (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    source_id VARCHAR(64) NOT NULL,
    source_family VARCHAR(64) NOT NULL,
    domain VARCHAR(64) NOT NULL,
    subject_key VARCHAR(256) NOT NULL,
    UNIQUE (match_id, source_id, domain, subject_key)
);

CREATE TABLE IF NOT EXISTS observation_revisions (
    id BIGSERIAL PRIMARY KEY,
    stream_id BIGINT NOT NULL REFERENCES observation_streams(id),
    revision INT NOT NULL CHECK (revision > 0),
    content_hash CHAR(64) NOT NULL,
    fact_status VARCHAR(32) NOT NULL CHECK (fact_status::TEXT IN (
        'value', 'confirmed_absent', 'unknown', 'not_published',
        'not_covered', 'not_applicable', 'conflict', 'stale'
    )),
    value_json JSONB,
    evidence_json JSONB NOT NULL,
    evidence_kind VARCHAR(32) NOT NULL CHECK (
        evidence_kind::TEXT IN ('source_observation', 'candidate', 'research_reconstruction')
    ),
    effective_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    first_acquired_at TIMESTAMPTZ NOT NULL,
    first_verified_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    UNIQUE (stream_id, revision),
    UNIQUE (id, stream_id),
    CHECK ((fact_status = 'value') = (value_json IS NOT NULL AND value_json <> 'null'::jsonb)),
    CHECK (fact_status <> 'confirmed_absent' OR evidence_json @> '{"coverage_complete":true}'),
    CHECK (first_verified_at >= first_acquired_at),
    CHECK (available_at >= ingested_at AND available_at >= first_acquired_at
           AND available_at >= first_verified_at
           AND (published_at IS NULL OR available_at >= published_at))
);

CREATE TABLE IF NOT EXISTS observation_checks (
    id BIGSERIAL PRIMARY KEY,
    stream_id BIGINT NOT NULL REFERENCES observation_streams(id),
    revision_id BIGINT,
    acquisition_status VARCHAR(32) NOT NULL CHECK (acquisition_status::TEXT IN (
        'success', 'not_requested', 'unavailable', 'quota_exhausted', 'forbidden', 'failed'
    )),
    acquired_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    FOREIGN KEY (revision_id, stream_id) REFERENCES observation_revisions(id, stream_id),
    CHECK ((acquisition_status = 'success') = (revision_id IS NOT NULL)),
    CHECK (available_at >= acquired_at AND available_at >= ingested_at),
    CHECK (valid_until IS NULL OR
           (acquisition_status = 'success' AND valid_until >= acquired_at))
);

CREATE INDEX IF NOT EXISTS idx_observation_revision_cutoff
    ON observation_revisions(stream_id, available_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_observation_check_cutoff
    ON observation_checks(stream_id, available_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_observation_check_revision
    ON observation_checks(revision_id, available_at DESC, id DESC);

-- Portable references selected in one MVCC view; no persisted native XID comparison.
CREATE TABLE IF NOT EXISTS observation_cutoffs (
    id UUID PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL,
    UNIQUE (id,as_of),
    include_reconstruction BOOLEAN NOT NULL,
    selections JSONB NOT NULL CHECK (
        jsonb_typeof(selections)='array' AND jsonb_array_length(selections) BETWEEN 1 AND 128
        AND octet_length(selections::text)<=262144
    ),
    content_hash CHAR(64) NOT NULL
);

CREATE OR REPLACE FUNCTION reject_observation_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'observation history is append-only' USING ERRCODE = '55000';
END $$;

-- Re-running a migration in a disposable schema is safe, without a trigger gap.
DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'observation_streams', 'observation_revisions', 'observation_checks', 'observation_cutoffs'
    ] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE
            tgrelid = relation_name::regclass AND tgname = 'observation_immutable') THEN
            EXECUTE format('CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION reject_observation_mutation()', relation_name);
        END IF;
    END LOOP;
END $$;
COMMIT;
