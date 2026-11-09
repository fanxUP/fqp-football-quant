-- P108-02: historical transfers are candidates; registration is separate evidence.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE FUNCTION player_registration_evidence_refs_valid(refs JSONB)
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
        ) AND jsonb_array_length(refs) = (
            SELECT count(DISTINCT item.value #>> '{}')
            FROM jsonb_array_elements(refs) AS item(value)
        )
    END
$$;

-- No source is approved by this migration. Each approval/suspension is a reviewed revision.
CREATE TABLE player_registration_authority_sources (
    source_name TEXT NOT NULL CHECK (
        source_name = lower(btrim(source_name))
        AND source_name ~ '^[a-z][a-z0-9_.-]{0,63}$'
    ),
    revision INTEGER NOT NULL CHECK (revision > 0),
    authority TEXT NOT NULL CHECK (authority IN (
        'competition_registry','governing_body_notice','official_club_registration'
    )),
    status TEXT NOT NULL CHECK (status IN ('approved','suspended')),
    source_reference TEXT NOT NULL CHECK (
        source_reference = btrim(source_reference)
        AND source_reference <> ''
        AND length(source_reference) <= 1024
    ),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    reviewed_by TEXT NOT NULL CHECK (
        reviewed_by = btrim(reviewed_by) AND reviewed_by <> '' AND length(reviewed_by) <= 128
    ),
    reviewed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_name,revision)
);

CREATE FUNCTION guard_player_registration_authority_revision()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_revision INTEGER;
BEGIN
    PERFORM 1
    FROM player_registration_authority_sources
    WHERE source_name = NEW.source_name
    ORDER BY revision DESC
    LIMIT 1
    FOR UPDATE;
    SELECT COALESCE(MAX(revision),0) + 1 INTO expected_revision
    FROM player_registration_authority_sources
    WHERE source_name = NEW.source_name;
    IF NEW.revision <> expected_revision THEN
        RAISE EXCEPTION 'player registration authority revisions must increase by one';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER player_registration_authority_revision_guard
    BEFORE INSERT ON player_registration_authority_sources
    FOR EACH ROW EXECUTE FUNCTION guard_player_registration_authority_revision();

CREATE FUNCTION reject_player_registration_authority_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'player registration authority revisions are append-only';
END
$$;

CREATE TRIGGER player_registration_authority_immutable
    BEFORE UPDATE OR DELETE ON player_registration_authority_sources
    FOR EACH ROW EXECUTE FUNCTION reject_player_registration_authority_mutation();
CREATE TRIGGER player_registration_authority_no_truncate
    BEFORE TRUNCATE ON player_registration_authority_sources
    FOR EACH STATEMENT EXECUTE FUNCTION reject_player_registration_authority_mutation();

CREATE VIEW player_registration_authority_current AS
SELECT DISTINCT ON (source_name)
    source_name,revision,authority,status,source_reference,content_sha256,reviewed_by,reviewed_at,created_at
FROM player_registration_authority_sources
ORDER BY source_name,revision DESC;

CREATE TABLE player_registration_facts (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL CHECK (
        source_name = lower(btrim(source_name))
        AND source_name ~ '^[a-z][a-z0-9_.-]{0,63}$'
    ),
    external_player_id TEXT NOT NULL CHECK (
        external_player_id = btrim(external_player_id)
        AND external_player_id <> ''
        AND length(external_player_id) <= 128
    ),
    source_competition_id TEXT NOT NULL CHECK (
        source_competition_id = btrim(source_competition_id)
        AND source_competition_id <> ''
        AND length(source_competition_id) <= 128
    ),
    source_season TEXT NOT NULL CHECK (
        source_season = btrim(source_season)
        AND source_season <> ''
        AND length(source_season) <= 64
    ),
    competition_season_id BIGINT REFERENCES competition_seasons(id) ON DELETE RESTRICT,
    source_record_key TEXT NOT NULL CHECK (
        source_record_key = btrim(source_record_key)
        AND source_record_key <> ''
        AND length(source_record_key) <= 512
    ),
    source_revision TEXT NOT NULL CHECK (
        source_revision = btrim(source_revision)
        AND source_revision <> ''
        AND length(source_revision) <= 128
    ),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('unknown','confirmed')),
    eligible BOOLEAN,
    source_authority TEXT NOT NULL CHECK (source_authority IN (
        'unknown','competition_registry','governing_body_notice','official_club_registration'
    )),
    valid_from DATE,
    valid_to DATE,
    source_published_at TIMESTAMPTZ,
    acquired_at TIMESTAMPTZ NOT NULL,
    evidence_refs JSONB NOT NULL CHECK (player_registration_evidence_refs_valid(evidence_refs)),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (
        source_name,external_player_id,source_competition_id,source_season,
        source_record_key,source_revision
    ),
    CHECK (valid_to IS NULL OR (valid_from IS NOT NULL AND valid_to > valid_from)),
    CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL)),
    CHECK (reviewed_by IS NULL OR (
        reviewed_by = btrim(reviewed_by) AND reviewed_by <> '' AND length(reviewed_by) <= 128
    )),
    CHECK ((status = 'unknown' AND eligible IS NULL) OR (status = 'confirmed' AND eligible IS NOT NULL)),
    CHECK (status <> 'confirmed' OR (
        competition_season_id IS NOT NULL
        AND valid_from IS NOT NULL
        AND valid_to IS NOT NULL
        AND source_authority <> 'unknown'
        AND reviewed_by IS NOT NULL
        AND reviewed_at IS NOT NULL
        AND reviewed_at >= acquired_at
    ))
);

CREATE INDEX idx_player_registration_fact_lookup
    ON player_registration_facts (
        source_name,external_player_id,source_competition_id,source_season,
        competition_season_id,acquired_at DESC,id DESC
    );

CREATE FUNCTION reject_player_registration_fact_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'player registration facts are append-only';
END
$$;

CREATE TRIGGER player_registration_facts_immutable
    BEFORE UPDATE OR DELETE ON player_registration_facts
    FOR EACH ROW EXECUTE FUNCTION reject_player_registration_fact_mutation();
CREATE TRIGGER player_registration_facts_no_truncate
    BEFORE TRUNCATE ON player_registration_facts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_player_registration_fact_mutation();

CREATE FUNCTION require_approved_player_registration_authority()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    source_authority TEXT;
    source_status TEXT;
BEGIN
    IF NEW.status <> 'confirmed' THEN
        RETURN NEW;
    END IF;
    SELECT authority,status INTO source_authority,source_status
    FROM player_registration_authority_current
    WHERE source_name = NEW.source_name;
    IF NOT FOUND OR source_status <> 'approved' OR source_authority <> NEW.source_authority THEN
        RAISE EXCEPTION 'confirmed registration fact requires an active reviewed authority source';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER player_registration_fact_authority_guard
    BEFORE INSERT ON player_registration_facts
    FOR EACH ROW EXECUTE FUNCTION require_approved_player_registration_authority();

-- Reuse the immutable, published history batch. Transfer data never means a current club or eligibility.
CREATE VIEW player_affiliation_candidates AS
SELECT
    r.batch_id,
    b.source_name,
    r.source_player_id::TEXT AS external_player_id,
    CASE WHEN identity.status = 'verified'
               AND identity.updated_at <= statement_timestamp()
               AND identity.reviewed_at <= statement_timestamp()
         THEN identity.player_id END AS canonical_player_id,
    COALESCE(identity.status,'unresolved') AS identity_status,
    r.source_record_key,
    b.content_sha256 AS source_batch_sha256,
    b.normalization_version,
    b.imported_at AS history_imported_at,
    r.value_json->>'effective_date' AS transfer_effective_date,
    r.value_json->>'end_date_normalized' AS transfer_end_date,
    r.value_json->>'from_team_id' AS source_from_team_id,
    r.value_json->>'from_name' AS source_from_team_name,
    r.value_json->>'to_team_id' AS source_to_team_id,
    r.value_json->>'to_name' AS source_to_team_name,
    'candidate_only'::TEXT AS affiliation_status,
    FALSE AS current_affiliation_confirmed,
    FALSE AS registration_eligibility_confirmed,
    r.value_json AS normalized_source_evidence
FROM football_history_available r
JOIN football_history_batches b ON b.id = r.batch_id
LEFT JOIN player_identity_links identity
    ON identity.source_name = b.source_name
   AND identity.external_player_id = r.source_player_id::TEXT
WHERE r.domain = 'player_transfers'
  AND b.source_name = 'titan007';

-- Latest captured revision per source record, with canonical identity only when verified.
CREATE VIEW player_registration_eligibility_current AS
SELECT DISTINCT ON (
    f.source_name,f.external_player_id,f.source_competition_id,f.source_season,
    f.competition_season_id,f.source_record_key
)
    f.id AS fact_id,
    f.source_name,
    f.external_player_id,
    CASE WHEN identity.status = 'verified'
               AND identity.updated_at <= statement_timestamp()
               AND identity.reviewed_at <= statement_timestamp()
         THEN identity.player_id END AS canonical_player_id,
    COALESCE(identity.status,'unresolved') AS identity_status,
    f.source_competition_id,
    f.source_season,
    f.competition_season_id,
    f.source_record_key,
    f.source_revision,
    f.content_sha256,
    f.status AS fact_status,
    CASE WHEN f.status = 'confirmed'
              AND authority.status = 'approved'
              AND authority.authority = f.source_authority
              AND authority.created_at <= statement_timestamp()
              AND authority.reviewed_at <= statement_timestamp()
              AND f.valid_from <= (statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::DATE
              AND (statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::DATE < f.valid_to
         THEN 'confirmed' ELSE 'unknown' END AS status,
    CASE WHEN f.status = 'confirmed'
              AND authority.status = 'approved'
              AND authority.authority = f.source_authority
              AND authority.created_at <= statement_timestamp()
              AND authority.reviewed_at <= statement_timestamp()
              AND f.valid_from <= (statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::DATE
              AND (statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::DATE < f.valid_to
         THEN f.eligible ELSE NULL END AS eligible,
    authority.status AS authority_status,
    authority.revision AS authority_revision,
    f.source_authority,
    f.valid_from,
    f.valid_to,
    f.source_published_at,
    f.acquired_at,
    f.evidence_refs,
    f.reviewed_by,
    f.reviewed_at
FROM player_registration_facts f
LEFT JOIN player_identity_links identity
    ON identity.source_name = f.source_name
   AND identity.external_player_id = f.external_player_id
LEFT JOIN player_registration_authority_current authority
    ON authority.source_name = f.source_name
WHERE f.acquired_at <= statement_timestamp()
  AND f.created_at <= statement_timestamp()
  AND (f.source_published_at IS NULL OR f.source_published_at <= statement_timestamp())
  AND (f.reviewed_at IS NULL OR f.reviewed_at <= statement_timestamp())
ORDER BY
    f.source_name,f.external_player_id,f.source_competition_id,f.source_season,
    f.competition_season_id,f.source_record_key,f.acquired_at DESC,f.id DESC;

REVOKE ALL ON player_registration_facts,player_affiliation_candidates,
    player_registration_eligibility_current,player_registration_authority_sources,
    player_registration_authority_current FROM PUBLIC;
REVOKE ALL ON SEQUENCE player_registration_facts_id_seq FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqp') THEN
        GRANT SELECT ON player_registration_facts,player_affiliation_candidates,
            player_registration_eligibility_current,player_registration_authority_sources,
            player_registration_authority_current TO fqp;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON player_registration_facts FROM fqp;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON player_registration_authority_sources FROM fqp;
        REVOKE ALL ON SEQUENCE player_registration_facts_id_seq FROM fqp;
    END IF;
END
$$;
