-- Preserve the market/model output before multidimensional feature adjustment.
ALTER TABLE model_predictions
    ADD COLUMN IF NOT EXISTS raw_model_probability NUMERIC(10,6);

UPDATE model_predictions
SET raw_model_probability = model_probability
WHERE raw_model_probability IS NULL;
