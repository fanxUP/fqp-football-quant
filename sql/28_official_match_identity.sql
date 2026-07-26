-- Strengthen Sporttery history identity.
-- The ticket-visible match number repeats weekly, so historical rows are
-- identified by business_date + official_match_code and, when available, the
-- immutable Sporttery matchId.
ALTER TABLE official_matches
    ADD COLUMN IF NOT EXISTS source_match_id VARCHAR(64);

UPDATE official_matches
SET source_match_id = NULLIF(raw_json->>'matchId', '')
WHERE source_match_id IS NULL
  AND NULLIF(raw_json->>'matchId', '') IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_official_matches_source_match_id
    ON official_matches (source_match_id)
    WHERE source_match_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'official_matches_display_code_format'
    ) THEN
        ALTER TABLE official_matches
            ADD CONSTRAINT official_matches_display_code_format
            CHECK (official_match_code ~ '^周[一二三四五六日][0-9]{3}$') NOT VALID;
    END IF;
END
$$;

ALTER TABLE official_matches
    VALIDATE CONSTRAINT official_matches_display_code_format;
