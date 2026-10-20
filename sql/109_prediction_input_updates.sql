-- P105: coalesced observation notifications; no historical backfill or scheduler.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

CREATE TABLE IF NOT EXISTS prediction_input_dirty_matches (
    match_id BIGINT PRIMARY KEY REFERENCES official_matches(id),
    input_version BIGINT NOT NULL CHECK (input_version > 0),
    last_check_id BIGINT NOT NULL REFERENCES observation_checks(id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_prediction_input_dirty_order
    ON prediction_input_dirty_matches(changed_at,match_id);

CREATE TABLE IF NOT EXISTS prediction_input_consumers (
    consumer_key VARCHAR(64) NOT NULL CHECK (consumer_key ~ '^[a-z][a-z0-9_./-]{0,63}$'),
    match_id BIGINT NOT NULL REFERENCES prediction_input_dirty_matches(match_id),
    completed_version BIGINT NOT NULL DEFAULT 0 CHECK (completed_version >= 0),
    lease_version BIGINT,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    attempt_count INT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    PRIMARY KEY (consumer_key,match_id),
    CHECK ((lease_version IS NULL AND lease_token IS NULL AND lease_until IS NULL)
        OR (lease_version IS NOT NULL AND lease_version > completed_version
            AND lease_token IS NOT NULL AND lease_until IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS prediction_input_consumptions (
    consumer_key VARCHAR(64) NOT NULL,
    match_id BIGINT NOT NULL,
    input_version BIGINT NOT NULL CHECK (input_version > 0),
    claim_token UUID NOT NULL,
    result_refs JSONB NOT NULL CHECK (
        jsonb_typeof(result_refs)='object' AND octet_length(result_refs::text)<=32768
    ),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (consumer_key,match_id,input_version),
    FOREIGN KEY (consumer_key,match_id)
        REFERENCES prediction_input_consumers(consumer_key,match_id)
);

-- Writers retain INSERT-only history privileges. This fixed-table trigger is
-- owned by the migration role; callers cannot invoke it as a general updater.
CREATE OR REPLACE FUNCTION notify_prediction_input_update()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $$
BEGIN
    INSERT INTO public.prediction_input_dirty_matches AS d
        (match_id,input_version,last_check_id,changed_at)
    SELECT s.match_id,1,NEW.id,clock_timestamp()
    FROM public.observation_streams s WHERE s.id=NEW.stream_id
    ON CONFLICT (match_id) DO UPDATE SET
        input_version=d.input_version+1,
        last_check_id=EXCLUDED.last_check_id,
        changed_at=EXCLUDED.changed_at;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION notify_prediction_input_update() FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE
        tgrelid='observation_checks'::regclass AND tgname='trg_prediction_input_dirty') THEN
        CREATE TRIGGER trg_prediction_input_dirty AFTER INSERT ON observation_checks
            FOR EACH ROW EXECUTE FUNCTION notify_prediction_input_update();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE
        tgrelid='prediction_input_consumptions'::regclass AND tgname='observation_immutable') THEN
        CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
            ON prediction_input_consumptions FOR EACH STATEMENT
            EXECUTE FUNCTION reject_observation_mutation();
    END IF;
END $$;
COMMIT;
