-- Date validation uses PL/pgSQL exception blocks (subtransactions), which
-- PostgreSQL cannot execute in parallel mode, including on the leader.
-- Keep the already-applied 120 checksum unchanged; correct only the attribute.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
ALTER FUNCTION football_history_odds_time_candidate(TEXT,TIMESTAMPTZ) PARALLEL UNSAFE;
