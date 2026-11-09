-- P108-01: source-scoped player identity mappings. No existing player rows are rewritten.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE FUNCTION player_identity_evidence_refs_valid(refs JSONB)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(refs) <> 'array' THEN FALSE
        WHEN jsonb_array_length(refs) NOT BETWEEN 1 AND 64 THEN FALSE
        ELSE NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(refs) AS item(value)
            WHERE jsonb_typeof(item.value) <> 'string'
               OR btrim(item.value #>> '{}') = ''
               OR length(item.value #>> '{}') > 1024
        )
    END
$$;

CREATE TABLE player_identity_links (
    source_name TEXT NOT NULL CHECK (
        source_name = lower(btrim(source_name))
        AND source_name ~ '^[a-z][a-z0-9_.-]{0,63}$'
    ),
    external_player_id TEXT NOT NULL CHECK (
        external_player_id = btrim(external_player_id)
        AND external_player_id <> ''
        AND length(external_player_id) <= 128
    ),
    player_id BIGINT REFERENCES players(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('unresolved', 'candidate', 'verified', 'rejected')),
    evidence_refs JSONB NOT NULL CHECK (player_identity_evidence_refs_valid(evidence_refs)),
    matching_method TEXT NOT NULL CHECK (
        matching_method = btrim(matching_method)
        AND matching_method <> ''
        AND length(matching_method) <= 64
    ),
    confidence NUMERIC(6,5) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_name, external_player_id),
    CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL)),
    CHECK (reviewed_by IS NULL OR (
        reviewed_by = btrim(reviewed_by) AND reviewed_by <> '' AND length(reviewed_by) <= 128
    )),
    CHECK (status <> 'unresolved' OR player_id IS NULL),
    CHECK (status <> 'verified' OR player_id IS NOT NULL),
    CHECK (status NOT IN ('verified', 'rejected') OR reviewed_by IS NOT NULL)
);

CREATE INDEX idx_player_identity_links_verified_player
    ON player_identity_links (player_id, source_name)
    WHERE status = 'verified';

CREATE TABLE player_identity_link_events (
    source_name TEXT NOT NULL,
    external_player_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    player_id BIGINT REFERENCES players(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('unresolved', 'candidate', 'verified', 'rejected')),
    evidence_refs JSONB NOT NULL CHECK (player_identity_evidence_refs_valid(evidence_refs)),
    matching_method TEXT NOT NULL CHECK (
        matching_method = btrim(matching_method)
        AND matching_method <> ''
        AND length(matching_method) <= 64
    ),
    confidence NUMERIC(6,5) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_name, external_player_id, revision),
    CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL)),
    CHECK (status <> 'unresolved' OR player_id IS NULL),
    CHECK (status NOT IN ('verified', 'rejected') OR reviewed_by IS NOT NULL),
    FOREIGN KEY (source_name, external_player_id)
        REFERENCES player_identity_links(source_name, external_player_id) ON DELETE RESTRICT
);

CREATE FUNCTION guard_player_identity_link()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'player identity mappings cannot be deleted; mark them unresolved or rejected';
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.revision <> 1 THEN
            RAISE EXCEPTION 'a new player identity mapping must start at revision 1';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.source_name IS DISTINCT FROM OLD.source_name
       OR NEW.external_player_id IS DISTINCT FROM OLD.external_player_id THEN
        RAISE EXCEPTION 'player identity source keys are immutable';
    END IF;
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'player identity creation time is immutable';
    END IF;
    IF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'player identity revisions must increase by exactly one';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision', 'updated_at'])
       IS NOT DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision', 'updated_at']) THEN
        RAISE EXCEPTION 'player identity revision must change mapping evidence or status';
    END IF;
    IF OLD.status = 'verified' THEN
        IF NEW.status = 'verified' AND NEW.player_id IS DISTINCT FROM OLD.player_id THEN
            RAISE EXCEPTION 'verified player identity cannot be remapped directly';
        END IF;
        IF NEW.status NOT IN ('verified', 'rejected', 'unresolved') THEN
            RAISE EXCEPTION 'verified player identity must be explicitly rejected or unresolved before remapping';
        END IF;
        IF NEW.status = 'rejected' AND NEW.player_id IS DISTINCT FROM OLD.player_id THEN
            RAISE EXCEPTION 'rejected identity must retain its prior canonical player';
        END IF;
        IF NEW.status = 'unresolved' AND NEW.player_id IS NOT NULL THEN
            RAISE EXCEPTION 'unresolved identity cannot retain a canonical player';
        END IF;
    END IF;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END
$$;

CREATE FUNCTION record_player_identity_link_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO player_identity_link_events (
        source_name, external_player_id, revision, player_id, status,
        evidence_refs, matching_method, confidence, reviewed_by, reviewed_at
    ) VALUES (
        NEW.source_name, NEW.external_player_id, NEW.revision, NEW.player_id, NEW.status,
        NEW.evidence_refs, NEW.matching_method, NEW.confidence, NEW.reviewed_by, NEW.reviewed_at
    );
    RETURN NEW;
END
$$;

CREATE FUNCTION reject_player_identity_event_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'player identity audit events are append-only';
END
$$;

CREATE TRIGGER player_identity_link_guard
    BEFORE INSERT OR UPDATE OR DELETE ON player_identity_links
    FOR EACH ROW EXECUTE FUNCTION guard_player_identity_link();
CREATE TRIGGER player_identity_link_audit
    AFTER INSERT OR UPDATE ON player_identity_links
    FOR EACH ROW EXECUTE FUNCTION record_player_identity_link_event();
CREATE TRIGGER player_identity_link_no_truncate
    BEFORE TRUNCATE ON player_identity_links
    FOR EACH STATEMENT EXECUTE FUNCTION reject_player_identity_event_mutation();
CREATE TRIGGER player_identity_link_events_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON player_identity_link_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_player_identity_event_mutation();

REVOKE ALL ON player_identity_links, player_identity_link_events FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqp') THEN
        EXECUTE 'GRANT SELECT ON player_identity_links TO fqp';
        EXECUTE 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON player_identity_links FROM fqp';
        EXECUTE 'REVOKE ALL ON player_identity_link_events FROM fqp';
    END IF;
END
$$;
