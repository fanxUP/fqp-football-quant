-- Preserve issue primary keys, fixture links and saved plans. No fabricated
-- historical issue rows or cross-game copying. Short lock timeout, transactional.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
DO $$
DECLARE key_name TEXT;
BEGIN
    FOR key_name IN
        SELECT c.conname FROM pg_constraint c
        WHERE c.conrelid='football_pool_issues'::regclass AND c.contype='u'
          AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute
              WHERE attrelid=c.conrelid AND attname='issue_no')]::SMALLINT[]
    LOOP
        EXECUTE format('ALTER TABLE football_pool_issues DROP CONSTRAINT %I', key_name);
    END LOOP;
END $$;
-- Older upserts could retain the first game_type while overwriting raw_json
-- with a different section. Only a new typed collection proves the namespace.
ALTER TABLE football_pool_issues ADD COLUMN IF NOT EXISTS source_game_type TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pool_game_issue
    ON football_pool_issues(game_type, issue_no);
CREATE INDEX IF NOT EXISTS idx_pool_official_fixture_identity
    ON official_matches(home_team_name, away_team_name, kickoff_time);
ALTER TABLE football_pool_issue_matches ADD COLUMN IF NOT EXISTS source_match_id TEXT;
-- The old parser sometimes stored estimateDrawTime as sale_stop_time. Keep the
-- original value in raw evidence, but never treat an estimate as an official stop.
UPDATE football_pool_issues SET
    raw_json=raw_json || jsonb_build_object('_pool_correction_v1',
        jsonb_build_object('old_sale_stop_time', sale_stop_time,
                          'reason','no explicit official sale-end field')),
    sale_stop_time=NULL, official_status='unknown'
WHERE sale_stop_time IS NOT NULL AND raw_json IS NOT NULL
  AND NOT (raw_json ?| ARRAY['saleEndTime','lotterySaleEndtime','lotterySaleEndTime']);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pool_saved_snapshot
    ON football_pool_combinations ((combination_json->>'snapshot_hash'))
    WHERE combination_json->>'schema_version'='football-pool/v2';
CREATE OR REPLACE FUNCTION protect_pool_snapshot() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.combination_json->>'schema_version'='football-pool/v2' THEN
        RAISE EXCEPTION 'saved pool snapshots are immutable; save a new version';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
DROP TRIGGER IF EXISTS immutable_pool_snapshot ON football_pool_combinations;
CREATE TRIGGER immutable_pool_snapshot BEFORE UPDATE OR DELETE ON football_pool_combinations
    FOR EACH ROW EXECUTE FUNCTION protect_pool_snapshot();
COMMIT;
