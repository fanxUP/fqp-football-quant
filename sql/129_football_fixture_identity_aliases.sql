-- Add a canonical read bridge for source-verified duplicate traditional fixtures.
-- This migration creates an empty table; a separately reviewed operation writes aliases.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_fixture_identity_aliases (
    alias_fixture_id BIGINT PRIMARY KEY REFERENCES football_fixtures(id),
    canonical_fixture_id BIGINT NOT NULL UNIQUE REFERENCES football_fixtures(id),
    source_name TEXT NOT NULL DEFAULT 'sporttery'
        CHECK (source_name = 'sporttery'),
    id_system TEXT NOT NULL DEFAULT 'jc.matchId'
        CHECK (id_system = 'jc.matchId'),
    source_match_id TEXT NOT NULL CHECK (btrim(source_match_id) <> ''),
    evidence JSONB NOT NULL CHECK (
        jsonb_typeof(evidence) = 'object'
        AND evidence <> '{}'::jsonb
        AND COALESCE(evidence->>'contract', '') = 'football-fixture-alias/v1'
        AND COALESCE(evidence->>'basis', '') = 'direct_sporttery_match_id'
        AND COALESCE(evidence->>'source_match_id', '') = source_match_id
        AND COALESCE(evidence->>'candidate_snapshot_sha256', '') ~ '^[a-f0-9]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (source_name,id_system,source_match_id)
        REFERENCES football_fixture_source_links(source_name,id_system,source_match_id),
    CHECK (alias_fixture_id <> canonical_fixture_id)
);

CREATE FUNCTION validate_football_fixture_identity_alias() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE has_season_membership BOOLEAN;
BEGIN
    -- Shared with IDENTITY_LOCK in scripts/football_fixture_identity.py.
    -- All endpoint validation and competing source/membership writes serialize.
    PERFORM pg_advisory_xact_lock(1263554640);

    IF EXISTS (
        SELECT 1 FROM football_fixture_identity_aliases
        WHERE alias_fixture_id=NEW.canonical_fixture_id
           OR canonical_fixture_id=NEW.alias_fixture_id
    ) THEN
        RAISE EXCEPTION 'Fixture identity aliases must be direct and cannot form chains';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM football_fixture_source_links
        WHERE source_name=NEW.source_name
          AND id_system=NEW.id_system
          AND source_match_id=NEW.source_match_id
          AND fixture_id=NEW.canonical_fixture_id
    ) OR NOT EXISTS (
        SELECT 1 FROM official_matches
        WHERE source_match_id=NEW.source_match_id
    ) THEN
        RAISE EXCEPTION 'Canonical fixture is not bound to this official Sporttery MatchId';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM football_pool_issue_matches
        WHERE fixture_id=NEW.alias_fixture_id
          AND identity_status='linked'
          AND source_result_source='sporttery_history_api'
    ) OR EXISTS (
        SELECT 1 FROM football_pool_issue_matches
        WHERE fixture_id=NEW.alias_fixture_id
          AND (identity_status IS DISTINCT FROM 'linked'
               OR source_result_source IS DISTINCT FROM 'sporttery_history_api')
    ) THEN
        RAISE EXCEPTION 'Alias fixture must contain only linked traditional Sporttery history memberships';
    END IF;

    IF EXISTS (
        SELECT 1 FROM football_fixture_source_links
        WHERE fixture_id=NEW.alias_fixture_id
          AND (source_name<>'sporttery'
               OR id_system !~ '^traditional\.(t14c|r9|bqc6|jq4)\.[0-9]+\.matchOrder$')
    ) OR NOT EXISTS (
        SELECT 1 FROM football_fixture_source_links
        WHERE fixture_id=NEW.alias_fixture_id
          AND source_name='sporttery'
          AND id_system ~ '^traditional\.(t14c|r9|bqc6|jq4)\.[0-9]+\.matchOrder$'
    ) THEN
        RAISE EXCEPTION 'Alias fixture may only have typed traditional MatchOrder source links';
    END IF;

    IF EXISTS (
        SELECT 1 FROM football_fixture_source_links l
        WHERE l.fixture_id=NEW.alias_fixture_id
          AND NOT EXISTS (
              SELECT 1
              FROM football_pool_issue_matches m
              JOIN football_pool_issues i ON i.id=m.issue_id
              WHERE m.fixture_id=NEW.alias_fixture_id
                AND m.identity_status='linked'
                AND m.source_result_source='sporttery_history_api'
                AND l.id_system='traditional.'||i.game_type||'.'||i.issue_no||'.matchOrder'
                AND l.source_match_id=m.match_order::text
          )
    ) THEN
        RAISE EXCEPTION 'Every alias source link must match an exact traditional issue slot';
    END IF;

    IF to_regclass('football_fixture_seasons') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM football_fixture_seasons WHERE fixture_id=$1)'
            INTO has_season_membership USING NEW.alias_fixture_id;
        IF has_season_membership THEN
            RAISE EXCEPTION 'Alias fixture cannot own a season membership';
        END IF;
    END IF;

    RETURN NEW;
END $$;

CREATE FUNCTION prevent_mutation_of_aliased_fixture_identity() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE old_fixture_id BIGINT; new_fixture_id BIGINT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        old_fixture_id := NULLIF(to_jsonb(OLD)->>'fixture_id','')::BIGINT;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        new_fixture_id := NULLIF(to_jsonb(NEW)->>'fixture_id','')::BIGINT;
    END IF;
    IF old_fixture_id IS NULL AND new_fixture_id IS NULL THEN
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;

    -- Match the identity lock used by the application writer. Acquiring it
    -- before the alias lookup closes insert-vs-alias races without locking
    -- pending pool rows that have no fixture identity yet.
    PERFORM pg_advisory_xact_lock(1263554640);

    IF TG_TABLE_NAME='football_pool_issue_matches' AND TG_OP='UPDATE' THEN
        IF EXISTS (
            SELECT 1 FROM football_fixture_identity_aliases
            WHERE alias_fixture_id IN (old_fixture_id,new_fixture_id)
        ) THEN
            IF OLD.fixture_id IS NOT DISTINCT FROM NEW.fixture_id
               AND OLD.identity_status IS NOT DISTINCT FROM NEW.identity_status
               AND OLD.source_result_source IS NOT DISTINCT FROM NEW.source_result_source
               AND OLD.issue_id IS NOT DISTINCT FROM NEW.issue_id
               AND OLD.match_order IS NOT DISTINCT FROM NEW.match_order THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'An aliased fixture cannot be changed';
        END IF;
        RETURN NEW;
    END IF;

    IF EXISTS (
        SELECT 1 FROM football_fixture_identity_aliases
        WHERE alias_fixture_id IN (old_fixture_id,new_fixture_id)
    ) THEN
        RAISE EXCEPTION 'An aliased fixture cannot be changed';
    END IF;

    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER prevent_aliased_fixture_source_link_changes
    BEFORE INSERT OR UPDATE OR DELETE ON football_fixture_source_links
    FOR EACH ROW EXECUTE FUNCTION prevent_mutation_of_aliased_fixture_identity();
CREATE TRIGGER prevent_aliased_fixture_membership_changes
    BEFORE INSERT OR UPDATE OR DELETE ON football_pool_issue_matches
    FOR EACH ROW EXECUTE FUNCTION prevent_mutation_of_aliased_fixture_identity();
DO $$ BEGIN
    IF to_regclass('football_fixture_seasons') IS NOT NULL THEN
        EXECUTE 'CREATE TRIGGER prevent_aliased_fixture_season_memberships
            BEFORE INSERT OR UPDATE OR DELETE ON football_fixture_seasons
            FOR EACH ROW EXECUTE FUNCTION prevent_mutation_of_aliased_fixture_identity()';
    END IF;
END $$;

CREATE FUNCTION prevent_changing_aliased_issue_namespace() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(1263554640);

    IF EXISTS (
        SELECT 1
        FROM football_pool_issue_matches m
        JOIN football_fixture_identity_aliases a ON a.alias_fixture_id=m.fixture_id
        WHERE m.issue_id=OLD.id
    ) THEN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'An issue namespace used by an aliased fixture is immutable';
        ELSIF OLD.game_type IS DISTINCT FROM NEW.game_type
           OR OLD.issue_no IS DISTINCT FROM NEW.issue_no THEN
            RAISE EXCEPTION 'An issue namespace used by an aliased fixture is immutable';
        END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER prevent_changing_aliased_issue_namespace
    BEFORE UPDATE OF game_type,issue_no OR DELETE ON football_pool_issues
    FOR EACH ROW EXECUTE FUNCTION prevent_changing_aliased_issue_namespace();

CREATE TRIGGER validate_football_fixture_identity_alias
    BEFORE INSERT ON football_fixture_identity_aliases
    FOR EACH ROW EXECUTE FUNCTION validate_football_fixture_identity_alias();
CREATE TRIGGER protect_football_fixture_identity_aliases
    BEFORE UPDATE OR DELETE ON football_fixture_identity_aliases
    FOR EACH ROW EXECUTE FUNCTION protect_football_fixture_identity();
CREATE TRIGGER protect_football_fixture_identity_aliases_truncate
    BEFORE TRUNCATE ON football_fixture_identity_aliases
    EXECUTE FUNCTION protect_football_fixture_identity();

CREATE OR REPLACE VIEW football_pool_fixture_catalog AS
SELECT im.id AS membership_id, i.id AS issue_id, i.game_type, i.issue_no,
       i.source_game_type, im.match_order,
       COALESCE(a.canonical_fixture_id,im.fixture_id) AS fixture_id,
       CASE WHEN a.alias_fixture_id IS NOT NULL THEN canonical_match.id
            ELSE im.match_id END AS official_match_id,
       im.identity_status, im.identity_evidence, im.league_name,
       im.home_team_name, im.away_team_name, im.kickoff_time,
       im.source_match_id, im.source_raw_json,
       i.source_game_no,i.source_game_no_source,
       im.kickoff_date, im.kickoff_time_precision, im.kickoff_evidence,
       im.source_full_home_goals, im.source_full_away_goals,
       im.source_half_home_goals, im.source_half_away_goals,
       im.source_product_result_code, im.source_result_semantics_key,
       im.source_result_source, im.source_result_evidence
FROM football_pool_issue_matches im
JOIN football_pool_issues i ON i.id = im.issue_id
LEFT JOIN football_fixture_identity_aliases a ON a.alias_fixture_id=im.fixture_id
LEFT JOIN football_fixture_source_links jc
  ON jc.fixture_id=a.canonical_fixture_id
 AND jc.source_name='sporttery' AND jc.id_system='jc.matchId'
LEFT JOIN official_matches canonical_match
  ON canonical_match.source_match_id=jc.source_match_id;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fqp') THEN
        GRANT SELECT,INSERT ON football_fixture_identity_aliases TO fqp;
    END IF;
END $$;
