-- Keep actual football-match result observations separate from lottery settlement facts.
-- Execute in the migration runner's transaction; never backfill source data here.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_fixture_result_facts (
    id BIGSERIAL PRIMARY KEY,
    fixture_id BIGINT NOT NULL REFERENCES football_fixtures(id),
    source_name TEXT NOT NULL CHECK (btrim(source_name) <> ''),
    id_system TEXT NOT NULL CHECK (btrim(id_system) <> ''),
    source_match_id TEXT NOT NULL CHECK (btrim(source_match_id) <> ''),
    actual_match_date DATE,
    actual_kickoff_at TIMESTAMPTZ,
    kickoff_time_precision TEXT NOT NULL DEFAULT 'unknown'
        CHECK (kickoff_time_precision IN ('second','minute','date_only','unknown')),
    match_status TEXT NOT NULL
        CHECK (match_status IN (
            'completed','shortened','abandoned','postponed','cancelled','awarded','unknown'
        )),
    score_basis TEXT NOT NULL
        CHECK (score_basis IN ('on_field','awarded','unknown')),
    score_period TEXT NOT NULL
        CHECK (score_period IN ('regulation','extra_time','penalties','unknown')),
    half_home_goals INTEGER CHECK (half_home_goals IS NULL OR half_home_goals >= 0),
    half_away_goals INTEGER CHECK (half_away_goals IS NULL OR half_away_goals >= 0),
    full_home_goals INTEGER CHECK (full_home_goals IS NULL OR full_home_goals >= 0),
    full_away_goals INTEGER CHECK (full_away_goals IS NULL OR full_away_goals >= 0),
    source_published_at TIMESTAMPTZ,
    source_payload JSONB NOT NULL CHECK (
        jsonb_typeof(source_payload) = 'object' AND source_payload <> '{}'::jsonb
    ),
    evidence JSONB NOT NULL CHECK (
        jsonb_typeof(evidence) = 'object'
        AND evidence <> '{}'::jsonb
        AND COALESCE(evidence->>'contract','') = 'football-match-result-fact/v1'
        AND jsonb_typeof(evidence->'identity') = 'object'
        AND jsonb_typeof(evidence->'source_reference') = 'object'
    ),
    source_payload_sha256 TEXT GENERATED ALWAYS AS (
        encode(sha256(jsonb_send(source_payload)),'hex')
    ) STORED,
    evidence_sha256 TEXT GENERATED ALWAYS AS (
        encode(sha256(jsonb_send(evidence)),'hex')
    ) STORED,
    model_eligible BOOLEAN GENERATED ALWAYS AS (
        actual_match_date IS NOT NULL
        AND match_status = 'completed'
        AND score_basis = 'on_field'
        AND score_period = 'regulation'
        AND full_home_goals IS NOT NULL
        AND full_away_goals IS NOT NULL
    ) STORED,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (source_name,id_system,source_match_id)
        REFERENCES football_fixture_source_links(source_name,id_system,source_match_id),
    UNIQUE (source_name,id_system,source_match_id,source_payload_sha256),
    CHECK ((half_home_goals IS NULL) = (half_away_goals IS NULL)),
    CHECK ((full_home_goals IS NULL) = (full_away_goals IS NULL)),
    CHECK (match_status <> 'completed' OR score_basis <> 'awarded'),
    CHECK (
        (kickoff_time_precision IN ('second','minute') AND actual_kickoff_at IS NOT NULL)
        OR (kickoff_time_precision IN ('date_only','unknown') AND actual_kickoff_at IS NULL)
    ),
    CHECK (kickoff_time_precision <> 'date_only' OR actual_match_date IS NOT NULL),
    CHECK (actual_kickoff_at IS NULL OR actual_match_date IS NOT NULL),
    CHECK (
        COALESCE(evidence->'identity'->>'source_name','') = source_name
        AND COALESCE(evidence->'identity'->>'id_system','') = id_system
        AND COALESCE(evidence->'identity'->>'source_match_id','') = source_match_id
        AND COALESCE(evidence->'identity'->>'fixture_id','') = fixture_id::text
    )
);

CREATE INDEX idx_fixture_result_facts_fixture_date
    ON football_fixture_result_facts(fixture_id,actual_match_date)
    WHERE actual_match_date IS NOT NULL;
CREATE INDEX idx_fixture_result_facts_model_eligible
    ON football_fixture_result_facts(fixture_id,actual_match_date)
    WHERE model_eligible;

CREATE FUNCTION validate_football_fixture_result_fact_source() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM football_fixture_source_links
        WHERE source_name=NEW.source_name
          AND id_system=NEW.id_system
          AND source_match_id=NEW.source_match_id
          AND fixture_id=NEW.fixture_id
    ) THEN
        RAISE EXCEPTION 'Result fact source identity is not bound to this shared fixture';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION protect_football_fixture_result_fact() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Football fixture result facts are append-only';
END $$;

CREATE TRIGGER validate_football_fixture_result_fact_source
    BEFORE INSERT ON football_fixture_result_facts
    FOR EACH ROW EXECUTE FUNCTION validate_football_fixture_result_fact_source();
CREATE TRIGGER protect_football_fixture_result_facts
    BEFORE UPDATE OR DELETE ON football_fixture_result_facts
    FOR EACH ROW EXECUTE FUNCTION protect_football_fixture_result_fact();
CREATE TRIGGER protect_football_fixture_result_facts_truncate
    BEFORE TRUNCATE ON football_fixture_result_facts
    EXECUTE FUNCTION protect_football_fixture_result_fact();

CREATE VIEW football_fixture_model_result_facts AS
SELECT id,fixture_id,source_name,id_system,source_match_id,actual_match_date,
       actual_kickoff_at,kickoff_time_precision,half_home_goals,half_away_goals,
       full_home_goals,full_away_goals,source_published_at,
       source_payload_sha256,evidence_sha256,recorded_at
FROM football_fixture_result_facts
WHERE model_eligible;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fqp') THEN
        GRANT SELECT,INSERT ON football_fixture_result_facts TO fqp;
        GRANT SELECT ON football_fixture_model_result_facts TO fqp;
        GRANT USAGE,SELECT ON SEQUENCE football_fixture_result_facts_id_seq TO fqp;
    END IF;
END $$;
