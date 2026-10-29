-- Supplementary league facts share PostgreSQL identities, never official sales/results.
-- Entire revisions publish atomically; prior published batches remain reproducible.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS football_team_source_links (
    source_name VARCHAR(64) NOT NULL,
    id_system VARCHAR(32) NOT NULL,
    source_team_id VARCHAR(64) NOT NULL,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    resolution_method VARCHAR(32) NOT NULL CHECK (resolution_method IN ('source_entity','verified_alias','manual')),
    evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_name,id_system,source_team_id)
);

CREATE TABLE IF NOT EXISTS league_reference_batches (
    id BIGSERIAL PRIMARY KEY,
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    source_name VARCHAR(64) NOT NULL,
    source_competition_id VARCHAR(64) NOT NULL,
    source_season VARCHAR(64) NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    source_as_of TIMESTAMPTZ,
    source_acquired_at TIMESTAMPTZ,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    state VARCHAR(16) NOT NULL DEFAULT 'building' CHECK (state IN ('building','published')),
    quality JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    UNIQUE (competition_season_id,source_name,content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_league_reference_latest ON league_reference_batches
    (competition_season_id,source_as_of DESC NULLS LAST,imported_at DESC,id DESC) WHERE state='published';

CREATE TABLE IF NOT EXISTS league_reference_fixtures (
    batch_id BIGINT NOT NULL REFERENCES league_reference_batches(id),
    source_match_id VARCHAR(64) NOT NULL,
    home_team_id BIGINT NOT NULL REFERENCES teams(id),
    away_team_id BIGINT NOT NULL REFERENCES teams(id),
    kickoff TIMESTAMPTZ,
    round_id VARCHAR(64),
    status VARCHAR(16) NOT NULL CHECK (status IN ('scheduled','live','finished','postponed','cancelled','unknown')),
    home_goals INTEGER CHECK (home_goals>=0),
    away_goals INTEGER CHECK (away_goals>=0),
    PRIMARY KEY (batch_id,source_match_id),
    CHECK (home_team_id<>away_team_id),
    CHECK (status<>'finished' OR (home_goals IS NOT NULL AND away_goals IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_league_reference_fixture_page ON league_reference_fixtures(batch_id,kickoff,source_match_id);
CREATE INDEX IF NOT EXISTS idx_league_reference_fixture_home ON league_reference_fixtures(batch_id,home_team_id);
CREATE INDEX IF NOT EXISTS idx_league_reference_fixture_away ON league_reference_fixtures(batch_id,away_team_id);

CREATE TABLE IF NOT EXISTS league_reference_standings (
    batch_id BIGINT NOT NULL REFERENCES league_reference_batches(id),
    scope VARCHAR(16) NOT NULL CHECK (scope IN ('all','home','away')),
    team_id BIGINT NOT NULL REFERENCES teams(id),
    rank INTEGER CHECK (rank>0), played INTEGER CHECK (played>=0),
    won INTEGER CHECK (won>=0), drawn INTEGER CHECK (drawn>=0), lost INTEGER CHECK (lost>=0),
    goals_for INTEGER CHECK (goals_for>=0), goals_against INTEGER CHECK (goals_against>=0),
    goal_difference INTEGER, points INTEGER, note TEXT,
    PRIMARY KEY (batch_id,scope,team_id)
);

CREATE OR REPLACE FUNCTION protect_league_reference_batch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' AND OLD.state='building' AND NEW.state='published'
       AND (to_jsonb(OLD)-'state')=(to_jsonb(NEW)-'state') THEN RETURN NEW; END IF;
    RAISE EXCEPTION 'League reference batches are immutable except atomic publication';
END $$;
CREATE OR REPLACE FUNCTION protect_league_reference_rows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'League reference revisions are immutable'; END IF;
    PERFORM 1 FROM league_reference_batches WHERE id=NEW.batch_id AND state='building' FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Cannot extend a published league reference batch'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER trg_protect_league_reference_batch BEFORE UPDATE OR DELETE ON league_reference_batches
    FOR EACH ROW EXECUTE FUNCTION protect_league_reference_batch();
CREATE OR REPLACE TRIGGER trg_protect_league_reference_fixtures BEFORE INSERT OR UPDATE OR DELETE ON league_reference_fixtures
    FOR EACH ROW EXECUTE FUNCTION protect_league_reference_rows();
CREATE OR REPLACE TRIGGER trg_protect_league_reference_standings BEFORE INSERT OR UPDATE OR DELETE ON league_reference_standings
    FOR EACH ROW EXECUTE FUNCTION protect_league_reference_rows();

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fqp') THEN
        GRANT SELECT ON football_team_source_links,league_reference_batches,league_reference_fixtures,league_reference_standings TO fqp;
        GRANT INSERT ON football_team_source_links,league_reference_batches,league_reference_fixtures,league_reference_standings TO fqp;
        GRANT UPDATE(state) ON league_reference_batches TO fqp;
        GRANT USAGE,SELECT ON SEQUENCE league_reference_batches_id_seq TO fqp;
    END IF;
END $$;
