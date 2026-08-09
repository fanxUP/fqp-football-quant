-- Existing installations may already have applied migration 72 before the
-- application role grants were added. Keep this migration idempotent.

GRANT SELECT, INSERT, UPDATE, DELETE ON team_glicko2_ratings TO fqp;
GRANT SELECT, INSERT, UPDATE, DELETE ON glicko2_update_logs TO fqp;
GRANT USAGE, SELECT ON SEQUENCE team_glicko2_ratings_id_seq TO fqp;
GRANT USAGE, SELECT ON SEQUENCE glicko2_update_logs_id_seq TO fqp;
