-- Remove derivatives that no longer have a valid, independently produced
-- prediction. These tables intentionally have no prediction_id foreign key,
-- so the integrity condition is enforced through the full decision identity.
DELETE FROM model_committee_votes vote
WHERE NOT EXISTS (
    SELECT 1
    FROM model_predictions prediction
    WHERE prediction.match_id = vote.match_id
      AND prediction.model_version_id = vote.model_version_id
      AND prediction.play_type = vote.play_type
      AND prediction.option_code = vote.option_code
      AND prediction.predict_time = vote.prediction_time
      AND prediction.validation_status = 'valid'
      AND COALESCE(
          (prediction.uncertainty_reason->>'model_independent')::boolean,
          false
      ) = true
);

DELETE FROM prediction_error_analysis analysis
WHERE NOT EXISTS (
    SELECT 1
    FROM model_predictions prediction
    WHERE prediction.id = analysis.prediction_id
      AND prediction.validation_status = 'valid'
      AND COALESCE(
          (prediction.uncertainty_reason->>'model_independent')::boolean,
          false
      ) = true
);

-- Evaluation metrics are reproducible and previously mixed market-seeded and
-- independent predictions. Clear the table; the evaluation job rebuilds it
-- from the guarded valid-independent query after deployment.
DELETE FROM market_efficiency_metrics;

DELETE FROM score_distribution_snapshots distribution
WHERE NOT EXISTS (
    SELECT 1
    FROM model_predictions prediction
    WHERE prediction.match_id = distribution.match_id
      AND prediction.model_version_id = distribution.model_version_id
      AND prediction.predict_time = distribution.prediction_time
      AND prediction.validation_status = 'valid'
      AND COALESCE(
          (prediction.uncertainty_reason->>'model_independent')::boolean,
          false
      ) = true
);

CREATE OR REPLACE FUNCTION enforce_valid_committee_vote_reference()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM model_predictions prediction
        WHERE prediction.match_id = NEW.match_id
          AND prediction.model_version_id = NEW.model_version_id
          AND prediction.play_type = NEW.play_type
          AND prediction.option_code = NEW.option_code
          AND prediction.predict_time = NEW.prediction_time
          AND prediction.validation_status = 'valid'
          AND COALESCE(
              (prediction.uncertainty_reason->>'model_independent')::boolean,
              false
          ) = true
    ) THEN
        RAISE EXCEPTION 'Committee vote requires a valid independent prediction'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_committee_vote_prediction_valid
    ON model_committee_votes;

CREATE TRIGGER trg_committee_vote_prediction_valid
BEFORE INSERT OR UPDATE ON model_committee_votes
FOR EACH ROW
EXECUTE FUNCTION enforce_valid_committee_vote_reference();
