SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

LOCK TABLE football_fixture_market_references IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT FROM football_fixture_market_references) THEN
        RAISE EXCEPTION 'Market references or collection receipts exist; keep migration 133 when rolling back the app';
    END IF;
END $$;
DROP TABLE football_fixture_market_references;
