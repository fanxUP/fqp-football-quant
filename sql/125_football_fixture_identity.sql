-- Identity bridge only: no invented JC records, season assignment or score copies.
-- Execute in the migration runner's transaction. Existing IDs/FKs stay intact.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_fixtures (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE football_fixture_source_links (
    source_name TEXT NOT NULL CHECK (btrim(source_name) <> ''),
    id_system TEXT NOT NULL CHECK (btrim(id_system) <> ''),
    source_match_id TEXT NOT NULL CHECK (btrim(source_match_id) <> ''),
    fixture_id BIGINT NOT NULL REFERENCES football_fixtures(id),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_name, id_system, source_match_id),
    UNIQUE (fixture_id, source_name, id_system)
);

ALTER TABLE football_pool_issue_matches
    ADD COLUMN fixture_id BIGINT REFERENCES football_fixtures(id),
    ADD COLUMN identity_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN identity_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN source_raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT pool_fixture_identity_state CHECK (
        (identity_status = 'linked' AND fixture_id IS NOT NULL)
        OR (identity_status IN ('pending','conflict') AND fixture_id IS NULL)
    ),
    ADD CONSTRAINT pool_fixture_evidence_object CHECK (
        jsonb_typeof(identity_evidence) = 'object' AND jsonb_typeof(source_raw_json) = 'object'
    );

CREATE INDEX idx_pool_shared_fixture ON football_pool_issue_matches(fixture_id)
    WHERE fixture_id IS NOT NULL;
CREATE INDEX idx_pool_fixture_exact_identity ON football_pool_issue_matches
    (league_name,home_team_name,away_team_name,kickoff_time)
    WHERE identity_status = 'linked';

CREATE TABLE football_pool_fixture_revisions (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL,
    match_order INT NOT NULL,
    fixture_id BIGINT REFERENCES football_fixtures(id),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    material_json JSONB NOT NULL CHECK (jsonb_typeof(material_json) = 'object'),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (issue_id,match_order)
        REFERENCES football_pool_issue_matches(issue_id,match_order),
    UNIQUE (issue_id,match_order,content_sha256)
);
CREATE INDEX idx_pool_fixture_revision_fixture ON football_pool_fixture_revisions(fixture_id)
    WHERE fixture_id IS NOT NULL;

-- Snapshot the old row before a replacement too, including pre-125 rows which
-- have no per-match raw JSON. Never pretend their legacy ID was source-verified.
CREATE FUNCTION record_pool_fixture_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE material JSONB; materials JSONB[];
BEGIN
    materials := ARRAY[to_jsonb(NEW)];
    IF TG_OP = 'UPDATE' THEN materials := ARRAY[to_jsonb(OLD)] || materials; END IF;
    FOREACH material IN ARRAY materials LOOP
        material := material - ARRAY['id','created_at','home_win_prob','draw_prob',
            'away_win_prob','upset_score','public_heat_home','public_heat_draw','public_heat_away'];
        INSERT INTO football_pool_fixture_revisions
            (issue_id,match_order,fixture_id,content_sha256,material_json)
        VALUES (NEW.issue_id,NEW.match_order,(material->>'fixture_id')::bigint,
            encode(sha256(convert_to(material::text,'UTF8')),'hex'),material)
        ON CONFLICT (issue_id,match_order,content_sha256) DO NOTHING;
    END LOOP;
    RETURN NEW;
END $$;
CREATE TRIGGER record_pool_fixture_revision AFTER INSERT OR UPDATE
    ON football_pool_issue_matches FOR EACH ROW EXECUTE FUNCTION record_pool_fixture_revision();

CREATE FUNCTION protect_football_fixture_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Fixture identities, source bindings and revisions are immutable';
END $$;
CREATE TRIGGER protect_football_fixtures BEFORE UPDATE OR DELETE ON football_fixtures
    FOR EACH ROW EXECUTE FUNCTION protect_football_fixture_identity();
CREATE TRIGGER protect_football_fixture_links BEFORE UPDATE OR DELETE ON football_fixture_source_links
    FOR EACH ROW EXECUTE FUNCTION protect_football_fixture_identity();
CREATE TRIGGER protect_pool_fixture_revisions BEFORE UPDATE OR DELETE ON football_pool_fixture_revisions
    FOR EACH ROW EXECUTE FUNCTION protect_football_fixture_identity();
CREATE TRIGGER protect_football_fixtures_truncate BEFORE TRUNCATE ON football_fixtures
    EXECUTE FUNCTION protect_football_fixture_identity();
CREATE TRIGGER protect_football_fixture_links_truncate BEFORE TRUNCATE ON football_fixture_source_links
    EXECUTE FUNCTION protect_football_fixture_identity();
CREATE TRIGGER protect_pool_fixture_revisions_truncate BEFORE TRUNCATE ON football_pool_fixture_revisions
    EXECUTE FUNCTION protect_football_fixture_identity();

-- One row per membership, not one per physical match. Consumers explicitly
-- count DISTINCT fixture_id and keep all game/issue/order memberships.
CREATE VIEW football_pool_fixture_catalog AS
SELECT im.id AS membership_id, i.id AS issue_id, i.game_type, i.issue_no,
       i.source_game_type, im.match_order, im.fixture_id, im.match_id AS official_match_id,
       im.identity_status, im.identity_evidence, im.league_name,
       im.home_team_name, im.away_team_name, im.kickoff_time,
       im.source_match_id, im.source_raw_json
FROM football_pool_issue_matches im JOIN football_pool_issues i ON i.id = im.issue_id;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqp') THEN
        GRANT SELECT,INSERT ON football_fixtures,football_fixture_source_links TO fqp;
        GRANT SELECT ON football_pool_fixture_revisions,football_pool_fixture_catalog TO fqp;
        GRANT USAGE,SELECT ON SEQUENCE football_fixtures_id_seq,football_pool_fixture_revisions_id_seq TO fqp;
        -- The revision trigger runs as the caller, with no SECURITY DEFINER.
        GRANT INSERT ON football_pool_fixture_revisions TO fqp;
    END IF;
END $$;
