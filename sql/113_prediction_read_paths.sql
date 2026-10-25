-- Latest means latest across every validation state, before eligibility filters.
-- The validation-leading and valid-only indexes cannot serve this boundary.
-- Seek each identity once instead of sorting every historical prediction.
-- This ordinary index build follows the existing atomic migration runner.
-- Before production apply, measure the build on copied data and its write lock;
-- if it cannot fit the maintenance/120s migration window, prebuild the same
-- index CONCURRENTLY outside a transaction and verify its definition/validity.
CREATE INDEX IF NOT EXISTS idx_predictions_identity_latest
    ON model_predictions (
        match_id, model_version_id, play_type, option_code,
        predict_time DESC, id DESC
    );
