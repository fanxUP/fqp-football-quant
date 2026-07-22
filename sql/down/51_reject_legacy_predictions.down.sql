ALTER TABLE model_predictions
    DROP CONSTRAINT IF EXISTS chk_model_predictions_valid_evidence;

ALTER TABLE model_predictions
    ALTER COLUMN validation_status SET DEFAULT 'valid',
    ALTER COLUMN calculation_version SET DEFAULT 'legacy';

-- Deleted legacy rows are intentionally not recreated. Restore the verified
-- pre-migration backup when historical row recovery is required.
