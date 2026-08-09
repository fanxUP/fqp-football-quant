-- The application role owns report orchestration, not report business facts.
-- Keep these grants explicit because the tables are created by the PostgreSQL owner.
GRANT SELECT, INSERT, UPDATE ON report_generation_runs TO fqp;
GRANT USAGE, SELECT ON SEQUENCE report_generation_runs_id_seq TO fqp;

GRANT SELECT, INSERT, UPDATE ON report_automation_settings TO fqp;
