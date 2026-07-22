-- Purge reproducible model artifacts created at or after official kickoff.
-- Ticket-referenced predictions are deliberately retained so evidence chains
-- never break silently; the contamination audit will keep flagging those rows.
DELETE FROM prediction_error_analysis pea
USING model_predictions mp, official_matches m
WHERE pea.prediction_id = mp.id
  AND m.id = mp.match_id
  AND mp.predict_time >= m.kickoff_time;

DELETE FROM model_committee_votes vote
USING official_matches m
WHERE m.id = vote.match_id
  AND vote.prediction_time >= m.kickoff_time;

DELETE FROM market_efficiency_metrics metric
USING official_matches m
WHERE m.id = metric.match_id
  AND metric.snapshot_time >= m.kickoff_time;

DELETE FROM model_predictions prediction
USING official_matches m
WHERE m.id = prediction.match_id
  AND prediction.predict_time >= m.kickoff_time
  AND NOT EXISTS (
      SELECT 1
      FROM simulation_ticket_items item
      WHERE item.model_prediction_id = prediction.id
  );
