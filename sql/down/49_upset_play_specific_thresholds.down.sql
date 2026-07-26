BEGIN;

DELETE FROM upset_rule_versions WHERE rule_key = 'upset-v2';
UPDATE upset_rule_versions
SET is_active = true,
    valid_to = NULL
WHERE rule_key = 'upset-v1';
DELETE FROM local_schema_migrations
WHERE filename = '49_upset_play_specific_thresholds.sql';

COMMIT;
