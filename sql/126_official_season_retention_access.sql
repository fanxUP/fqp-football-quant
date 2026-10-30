-- Migration124 created this table as the migration owner, but runtime storage,
-- its invoker-rights trigger and season reconciliation use the fqp role.
-- Keep applied migration checksums, table ownership and historical rows intact.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

GRANT SELECT, INSERT, UPDATE ON official_event_season_retention TO fqp;
