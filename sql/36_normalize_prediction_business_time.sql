-- official_matches.kickoff_time and official odds snapshots use naive
-- Asia/Shanghai wall-clock timestamps. Earlier model jobs used the container's
-- UTC wall clock. Preserve each batch's shared timestamp while converting only
-- rows whose stored prediction time still matches the UTC creation instant.
UPDATE model_predictions
SET predict_time = predict_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai'
WHERE created_at IS NOT NULL
  AND ABS(EXTRACT(EPOCH FROM (predict_time - created_at))) < 300;

UPDATE model_committee_votes
SET prediction_time = prediction_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai'
WHERE created_at IS NOT NULL
  AND ABS(EXTRACT(EPOCH FROM (prediction_time - created_at))) < 300;
