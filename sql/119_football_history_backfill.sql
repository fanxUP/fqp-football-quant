-- Cleaned historical facts in the shared database. No legacy projections change.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_history_batches (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    normalization_version TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    state TEXT NOT NULL DEFAULT 'building' CHECK (state IN ('building','published')),
    manifest JSONB NOT NULL,
    UNIQUE (source_name, content_sha256)
);

CREATE TABLE football_history_matches (
    batch_id BIGINT NOT NULL REFERENCES football_history_batches(id),
    source_match_id BIGINT NOT NULL CHECK (source_match_id > 0),
    source_competition_id BIGINT,
    source_season TEXT,
    kickoff_at TIMESTAMPTZ NOT NULL,
    match_status TEXT NOT NULL,
    source_home_team_id BIGINT NOT NULL CHECK (source_home_team_id > 0),
    source_away_team_id BIGINT NOT NULL CHECK (source_away_team_id > 0),
    home_name TEXT,
    away_name TEXT,
    home_goals INTEGER CHECK (home_goals >= 0),
    away_goals INTEGER CHECK (away_goals >= 0),
    source_updated_at TIMESTAMPTZ,
    source_metadata JSONB NOT NULL,
    home_team_id BIGINT REFERENCES teams(id),
    away_team_id BIGINT REFERENCES teams(id),
    official_match_id BIGINT REFERENCES official_matches(id),
    PRIMARY KEY (batch_id,source_match_id),
    CHECK (source_home_team_id <> source_away_team_id),
    CHECK (match_status <> 'finished' OR (home_goals IS NOT NULL AND away_goals IS NOT NULL))
);
CREATE INDEX idx_football_history_match_home ON football_history_matches(home_team_id,kickoff_at);
CREATE INDEX idx_football_history_match_away ON football_history_matches(away_team_id,kickoff_at);
CREATE INDEX idx_football_history_match_official ON football_history_matches(official_match_id)
    WHERE official_match_id IS NOT NULL;

CREATE TABLE football_history_records (
    batch_id BIGINT NOT NULL REFERENCES football_history_batches(id),
    domain TEXT NOT NULL CHECK (domain IN ('match_stats','events','lineups','predicted_lineups',
        'match_injuries','player_transfers','player_stats','player_appearances','odds','odds_history')),
    source_record_key TEXT NOT NULL,
    source_match_id BIGINT,
    source_player_id BIGINT CHECK (source_player_id > 0),
    side TEXT CHECK (side IN ('home','away')),
    origin TEXT NOT NULL CHECK (origin IN ('reported','prediction','derived','market')),
    value_json JSONB NOT NULL CHECK (jsonb_typeof(value_json)='object'),
    PRIMARY KEY (batch_id,domain,source_record_key),
    FOREIGN KEY (batch_id,source_match_id)
        REFERENCES football_history_matches(batch_id,source_match_id),
    CHECK ((domain='player_transfers') = (source_match_id IS NULL))
);
CREATE INDEX idx_football_history_record_match ON football_history_records(batch_id,source_match_id,domain)
    WHERE source_match_id IS NOT NULL;
CREATE INDEX idx_football_history_record_player ON football_history_records(source_player_id,domain)
    WHERE source_player_id IS NOT NULL;

CREATE FUNCTION protect_football_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME='football_history_batches' THEN
        IF TG_OP='UPDATE' AND OLD.state='building' AND NEW.state='published'
           AND (to_jsonb(OLD)-'state')=(to_jsonb(NEW)-'state') THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Historical batches are immutable except publication';
    END IF;
    IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Historical facts are immutable'; END IF;
    PERFORM 1 FROM football_history_batches WHERE id=NEW.batch_id AND state='building' FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Cannot extend a published history batch'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER protect_football_history_batch BEFORE UPDATE OR DELETE ON football_history_batches
    FOR EACH ROW EXECUTE FUNCTION protect_football_history();
CREATE TRIGGER protect_football_history_matches BEFORE INSERT OR UPDATE OR DELETE ON football_history_matches
    FOR EACH ROW EXECUTE FUNCTION protect_football_history();
CREATE TRIGGER protect_football_history_records BEFORE INSERT OR UPDATE OR DELETE ON football_history_records
    FOR EACH ROW EXECUTE FUNCTION protect_football_history();

CREATE FUNCTION reject_football_history_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Historical publication cannot be truncated';
END $$;
CREATE TRIGGER protect_football_history_batch_truncate BEFORE TRUNCATE ON football_history_batches
    EXECUTE FUNCTION reject_football_history_truncate();
CREATE TRIGGER protect_football_history_match_truncate BEFORE TRUNCATE ON football_history_matches
    EXECUTE FUNCTION reject_football_history_truncate();
CREATE TRIGGER protect_football_history_record_truncate BEFORE TRUNCATE ON football_history_records
    EXECUTE FUNCTION reject_football_history_truncate();

-- Consumers require a published batch, and must deliberately choose each domain.
CREATE VIEW football_history_available AS
SELECT r.*,m.kickoff_at,m.match_status,m.home_team_id,m.away_team_id,m.official_match_id,
       b.source_name,b.imported_at,b.normalization_version
FROM football_history_records r
JOIN football_history_batches b ON b.id=r.batch_id AND b.state='published'
LEFT JOIN football_history_matches m ON m.batch_id=r.batch_id AND m.source_match_id=r.source_match_id;

GRANT SELECT ON football_history_batches,football_history_matches,football_history_records,
    football_history_available TO fqp;
-- Only an explicit migration/import owner writes history; normal application is read-only.
