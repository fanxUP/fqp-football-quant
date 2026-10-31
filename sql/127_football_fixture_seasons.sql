-- Add evidence-backed, competition-specific seasons without rewriting shared
-- calendar-year seasons or immutable published historical facts.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_competition_season_sources (
    id BIGSERIAL PRIMARY KEY,
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    source_name TEXT NOT NULL CHECK (btrim(source_name) <> ''),
    id_system TEXT NOT NULL CHECK (btrim(id_system) <> ''),
    source_competition_id TEXT NOT NULL CHECK (btrim(source_competition_id) <> ''),
    source_season_id TEXT NOT NULL CHECK (btrim(source_season_id) <> ''),
    planned_start_date DATE NOT NULL,
    planned_end_date DATE NOT NULL CHECK (planned_end_date >= planned_start_date),
    source_timezone TEXT NOT NULL CHECK (btrim(source_timezone) <> ''),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_name,id_system,source_competition_id,source_season_id),
    UNIQUE (competition_season_id,source_name,id_system)
);

CREATE TABLE football_fixture_seasons (
    fixture_id BIGINT PRIMARY KEY REFERENCES football_fixtures(id),
    season_source_id BIGINT NOT NULL REFERENCES football_competition_season_sources(id),
    source_name TEXT NOT NULL,
    match_id_system TEXT NOT NULL,
    source_match_id TEXT NOT NULL,
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (source_name,match_id_system,source_match_id)
        REFERENCES football_fixture_source_links(source_name,id_system,source_match_id)
);
CREATE INDEX idx_football_fixture_seasons_source ON football_fixture_seasons(season_source_id,fixture_id);

-- Source bindings are immutable (125), so a SELECT is sufficient; no new
-- UPDATE grant on football_fixture_source_links is needed for row locks.
CREATE FUNCTION check_football_fixture_season_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM football_fixture_source_links
        WHERE source_name=NEW.source_name AND id_system=NEW.match_id_system
          AND source_match_id=NEW.source_match_id AND fixture_id=NEW.fixture_id) THEN
        RAISE EXCEPTION 'Season membership source does not identify this fixture';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_football_fixture_season_source BEFORE INSERT ON football_fixture_seasons
    FOR EACH ROW EXECUTE FUNCTION check_football_fixture_season_source();

CREATE FUNCTION protect_football_season_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Verified season sources and fixture memberships are immutable';
END $$;
CREATE TRIGGER protect_football_season_sources BEFORE UPDATE OR DELETE ON football_competition_season_sources
    FOR EACH ROW EXECUTE FUNCTION protect_football_season_identity();
CREATE TRIGGER protect_football_fixture_seasons BEFORE UPDATE OR DELETE ON football_fixture_seasons
    FOR EACH ROW EXECUTE FUNCTION protect_football_season_identity();
CREATE TRIGGER protect_football_season_sources_truncate BEFORE TRUNCATE ON football_competition_season_sources
    EXECUTE FUNCTION protect_football_season_identity();
CREATE TRIGGER protect_football_fixture_seasons_truncate BEFORE TRUNCATE ON football_fixture_seasons
    EXECUTE FUNCTION protect_football_season_identity();

-- Unverified legacy calendar-year/World Cup relationships are not projected.
-- Dates describe the source's planned season, never prove match membership.
CREATE VIEW football_fixture_season_catalog AS
SELECT m.fixture_id,s.competition_season_id,cs.competition_id,cs.season_id,
       c.competition_code,c.competition_name_cn,y.season_code,y.season_name,
       s.source_name AS season_source_name,s.id_system AS season_id_system,
       s.source_competition_id,s.source_season_id,
       s.planned_start_date,s.planned_end_date,s.source_timezone,
       m.source_name,m.match_id_system,m.source_match_id,
       s.evidence AS season_evidence,m.evidence AS membership_evidence
FROM football_fixture_seasons m
JOIN football_competition_season_sources s ON s.id=m.season_source_id
JOIN competition_seasons cs ON cs.id=s.competition_season_id
JOIN competitions c ON c.id=cs.competition_id
JOIN seasons y ON y.id=cs.season_id;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fqp') THEN
        GRANT SELECT,INSERT ON football_competition_season_sources,football_fixture_seasons TO fqp;
        GRANT SELECT ON football_fixture_season_catalog TO fqp;
        GRANT USAGE,SELECT ON SEQUENCE football_competition_season_sources_id_seq TO fqp;
    END IF;
END $$;
