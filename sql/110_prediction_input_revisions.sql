-- P105 input-readiness decisions. Model outputs/run artifacts remain separate.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
CREATE TABLE IF NOT EXISTS prediction_input_revisions (
    id BIGSERIAL PRIMARY KEY,
    consumer_key VARCHAR(64) NOT NULL,
    match_id BIGINT NOT NULL,
    input_version BIGINT NOT NULL CHECK (input_version > 0),
    play_type VARCHAR(8) NOT NULL CHECK (play_type IN ('spf','rqspf')),
    feature_batch_id BIGINT NOT NULL REFERENCES feature_batches(id),
    observation_cutoff_id UUID NOT NULL REFERENCES observation_cutoffs(id),
    decision JSONB NOT NULL CHECK (jsonb_typeof(decision)='object' AND octet_length(decision::text)<=131072),
    official_context JSONB NOT NULL CHECK (jsonb_typeof(official_context)='object' AND octet_length(official_context::text)<=32768),
    research_only BOOLEAN NOT NULL,
    invalidation_reasons JSONB NOT NULL CHECK (jsonb_typeof(invalidation_reasons)='array'),
    valid_until TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (consumer_key,match_id,input_version),
    FOREIGN KEY (consumer_key,match_id) REFERENCES prediction_input_consumers(consumer_key,match_id)
);
-- One configured consumer key represents one play/profile contract. Changing
-- that contract requires a new configured version, not arbitrary request keys.
CREATE INDEX IF NOT EXISTS idx_prediction_input_revision_expiry
    ON prediction_input_revisions(valid_until,match_id,input_version);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='prediction_input_revisions'::regclass
        AND tgname='observation_immutable') THEN
        CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
            ON prediction_input_revisions FOR EACH STATEMENT EXECUTE FUNCTION reject_observation_mutation();
    END IF;
END $$;

-- Keep revisions and trigger execution under the dedicated no-login owner.
ALTER TABLE prediction_input_revisions OWNER TO fqp_observation_owner;
ALTER SEQUENCE prediction_input_revisions_id_seq OWNER TO fqp_observation_owner;

-- Revisions are append-only; the runtime needs only read/insert and sequence use.
GRANT SELECT, INSERT ON prediction_input_revisions TO fqp;
GRANT USAGE ON SEQUENCE prediction_input_revisions_id_seq TO fqp;

-- Only matches already observed participate; no historical queue backfill.
-- Sorted old/new IDs also cover a source correcting a row's match binding.
CREATE OR REPLACE FUNCTION notify_prediction_official_update()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE old_match BIGINT; new_match BIGINT; mid BIGINT;
BEGIN
    IF TG_OP='UPDATE' AND OLD IS NOT DISTINCT FROM NEW THEN RETURN NEW; END IF;
    IF TG_TABLE_NAME='official_matches' THEN
        old_match=OLD.id; new_match=NEW.id;
    ELSE
        IF TG_OP<>'INSERT' THEN old_match=OLD.match_id; END IF;
        IF TG_OP<>'DELETE' THEN new_match=NEW.match_id; END IF;
    END IF;
    FOR mid IN SELECT DISTINCT x FROM unnest(ARRAY[old_match,new_match]) x WHERE x IS NOT NULL ORDER BY x LOOP
        UPDATE public.prediction_input_dirty_matches SET input_version=input_version+1,
            changed_at=clock_timestamp() WHERE match_id=mid;
    END LOOP;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION notify_prediction_official_update() FROM PUBLIC;
ALTER FUNCTION notify_prediction_official_update() OWNER TO fqp_observation_owner;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='official_matches'::regclass
        AND tgname='trg_prediction_official_dirty') THEN
        CREATE TRIGGER trg_prediction_official_dirty AFTER UPDATE OF business_date,official_match_code,
            source_match_id,home_team_name,away_team_name,kickoff_time,sale_stop_time,sale_status,match_status
            ON official_matches FOR EACH ROW EXECUTE FUNCTION notify_prediction_official_update();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='official_markets'::regclass
        AND tgname='trg_prediction_official_dirty') THEN
        CREATE TRIGGER trg_prediction_official_dirty AFTER INSERT OR UPDATE OR DELETE
            ON official_markets FOR EACH ROW EXECUTE FUNCTION notify_prediction_official_update();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='official_odds_snapshots'::regclass
        AND tgname='trg_prediction_official_dirty') THEN
        CREATE TRIGGER trg_prediction_official_dirty AFTER INSERT OR UPDATE OR DELETE
            ON official_odds_snapshots FOR EACH ROW EXECUTE FUNCTION notify_prediction_official_update();
    END IF;
END $$;
COMMIT;
