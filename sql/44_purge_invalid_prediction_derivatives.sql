-- Remove decisions and analytical derivatives built from predictions that
-- failed the metric-integrity gate. Real tickets and official data are not in
-- scope. The temporary key tables make the cleanup deterministic and keep all
-- dependent deletes inside the migration session. The local migration runner
-- wraps this file in a transaction, while CI executes one file per session, so
-- the temporary tables are dropped explicitly at the end instead of relying
-- on ON COMMIT DROP.
CREATE TEMP TABLE invalid_prediction_cleanup AS
SELECT id, match_id, model_version_id, play_type, option_code,
       predict_time, model_probability
FROM model_predictions
WHERE validation_status = 'invalid';

CREATE TEMP TABLE invalid_ticket_cleanup AS
SELECT DISTINCT item.ticket_id
FROM simulation_ticket_items item
JOIN invalid_prediction_cleanup bad ON bad.id = item.model_prediction_id;

CREATE TEMP TABLE invalid_budget_cleanup AS
SELECT DISTINCT ticket.budget_plan_id
FROM simulation_tickets ticket
JOIN invalid_ticket_cleanup bad ON bad.ticket_id = ticket.id
WHERE ticket.budget_plan_id IS NOT NULL;

DELETE FROM evidence_chain_audit_logs audit
WHERE audit.prediction_id IN (SELECT id FROM invalid_prediction_cleanup)
   OR audit.ticket_id IN (SELECT ticket_id FROM invalid_ticket_cleanup);

DELETE FROM prediction_error_analysis analysis
WHERE analysis.prediction_id IN (SELECT id FROM invalid_prediction_cleanup);

DELETE FROM model_committee_votes vote
USING invalid_prediction_cleanup bad
WHERE vote.match_id = bad.match_id
  AND vote.model_version_id = bad.model_version_id
  AND vote.play_type = bad.play_type
  AND vote.option_code = bad.option_code
  AND vote.prediction_time = bad.predict_time
  AND vote.model_probability IS NOT DISTINCT FROM bad.model_probability;

DELETE FROM market_efficiency_metrics metric
USING invalid_prediction_cleanup bad
WHERE metric.match_id = bad.match_id
  AND metric.model_version_id = bad.model_version_id
  AND metric.play_type = bad.play_type
  AND metric.option_code = bad.option_code
  AND metric.snapshot_time = bad.predict_time
  AND metric.model_probability IS NOT DISTINCT FROM bad.model_probability;

DELETE FROM score_distribution_snapshots distribution
USING invalid_prediction_cleanup bad
WHERE distribution.match_id = bad.match_id
  AND distribution.model_version_id = bad.model_version_id
  AND distribution.prediction_time = bad.predict_time;

DELETE FROM ticket_settlements settlement
WHERE settlement.ticket_source = 'simulation'
  AND settlement.ticket_id IN (SELECT ticket_id FROM invalid_ticket_cleanup);

DELETE FROM simulation_ticket_items item
WHERE item.ticket_id IN (SELECT ticket_id FROM invalid_ticket_cleanup);

DELETE FROM simulation_tickets ticket
WHERE ticket.id IN (SELECT ticket_id FROM invalid_ticket_cleanup);

DELETE FROM model_predictions prediction
WHERE prediction.id IN (SELECT id FROM invalid_prediction_cleanup);

DELETE FROM daily_budget_plans plan
WHERE plan.id IN (SELECT budget_plan_id FROM invalid_budget_cleanup)
  AND NOT EXISTS (
      SELECT 1 FROM simulation_tickets ticket
      WHERE ticket.budget_plan_id = plan.id
  );

-- Reconcile review numbers from the surviving source rows. Free-text summaries
-- are replaced because their old narrative may contain the removed figures.
WITH prediction_daily AS (
    SELECT match.business_date AS review_date,
           COUNT(DISTINCT prediction.match_id) AS recommended_match_count
    FROM model_predictions prediction
    JOIN official_matches match ON match.id = prediction.match_id
    WHERE prediction.validation_status = 'valid'
      AND prediction.predict_time < match.kickoff_time
    GROUP BY match.business_date
), ticket_daily AS (
    SELECT (ticket.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
               AS review_date,
           COUNT(*) AS ticket_count,
           COALESCE(SUM(ticket.suggested_stake), 0) AS suggested_stake
    FROM simulation_tickets ticket
    GROUP BY 1
), settlement_daily AS (
    SELECT (settlement.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
               AS review_date,
           COALESCE(SUM(settlement.stake_amount), 0) AS settled_stake,
           COALESCE(SUM(settlement.prize_amount), 0) AS prize,
           COALESCE(SUM(settlement.profit_loss), 0) AS profit_loss
    FROM ticket_settlements settlement
    WHERE settlement.ticket_source = 'simulation'
    GROUP BY 1
), review_values AS (
    SELECT review.id,
           COALESCE(prediction.recommended_match_count, 0) AS recommended_match_count,
           COALESCE(ticket.ticket_count, 0) AS ticket_count,
           COALESCE(ticket.suggested_stake, 0) AS suggested_stake,
           COALESCE(settlement.settled_stake, 0) AS settled_stake,
           COALESCE(settlement.prize, 0) AS prize,
           COALESCE(settlement.profit_loss, 0) AS profit_loss
    FROM daily_reviews review
    LEFT JOIN prediction_daily prediction ON prediction.review_date = review.review_date
    LEFT JOIN ticket_daily ticket ON ticket.review_date = review.review_date
    LEFT JOIN settlement_daily settlement ON settlement.review_date = review.review_date
)
UPDATE daily_reviews review
SET recommended_match_count = values.recommended_match_count,
    simulation_ticket_count = values.ticket_count,
    suggested_stake = values.suggested_stake,
    simulation_prize = values.prize,
    simulation_profit_loss = values.profit_loss,
    simulation_roi = CASE
        WHEN values.settled_stake > 0
        THEN values.profit_loss / values.settled_stake
        ELSE 0
    END,
    summary_text = '已清理无效预测及其 Agent 票据，本日数据已重新统计。',
    next_day_adjustment = '后续决策仅允许引用 validation_status=valid 的预测。'
FROM review_values values
WHERE values.id = review.id;

-- Rebuild the Agent side of daily and cumulative competition statistics while
-- preserving the independently sourced user figures.
WITH agent_daily AS (
    SELECT snapshot.id,
           COALESCE((
               SELECT SUM(ticket.suggested_stake)
               FROM simulation_tickets ticket
               WHERE (ticket.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                     = snapshot.snapshot_date
                 AND ticket.ticket_status IN ('generated', 'activated', 'settled')
           ), 0) AS daily_stake,
           COALESCE((
               SELECT SUM(settlement.prize_amount)
               FROM ticket_settlements settlement
               WHERE settlement.ticket_source = 'simulation'
                 AND (settlement.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                     = snapshot.snapshot_date
           ), 0) AS daily_prize,
           COALESCE((
               SELECT SUM(settlement.profit_loss)
               FROM ticket_settlements settlement
               WHERE settlement.ticket_source = 'simulation'
                 AND (settlement.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                     = snapshot.snapshot_date
           ), 0) AS daily_profit_loss,
           COALESCE((
               SELECT COUNT(*)
               FROM simulation_tickets ticket
               WHERE (ticket.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                     = snapshot.snapshot_date
                 AND ticket.ticket_status IN ('generated', 'activated', 'settled')
           ), 0) AS ticket_count
    FROM competition_daily_snapshots snapshot
)
UPDATE competition_daily_snapshots snapshot
SET agent_daily_stake = daily.daily_stake,
    agent_daily_prize = daily.daily_prize,
    agent_daily_profit_loss = daily.daily_profit_loss,
    agent_daily_roi = CASE
        WHEN daily.daily_stake > 0 THEN daily.daily_profit_loss / daily.daily_stake
        ELSE 0
    END,
    agent_budget_usage_rate = daily.daily_stake / 500.0,
    agent_ticket_count = daily.ticket_count
FROM agent_daily daily
WHERE daily.id = snapshot.id;

WITH cumulative AS (
    SELECT snapshot.id,
           SUM(snapshot.agent_daily_stake) OVER (
               PARTITION BY snapshot.round_id ORDER BY snapshot.snapshot_date
           ) AS cumulative_stake,
           SUM(snapshot.agent_daily_prize) OVER (
               PARTITION BY snapshot.round_id ORDER BY snapshot.snapshot_date
           ) AS cumulative_prize
    FROM competition_daily_snapshots snapshot
)
UPDATE competition_daily_snapshots snapshot
SET agent_cumulative_stake = cumulative.cumulative_stake,
    agent_cumulative_prize = cumulative.cumulative_prize,
    agent_cumulative_roi = CASE
        WHEN cumulative.cumulative_stake > 0
        THEN (cumulative.cumulative_prize - cumulative.cumulative_stake)
             / cumulative.cumulative_stake
        ELSE 0
    END
FROM cumulative
WHERE cumulative.id = snapshot.id;

WITH round_totals AS (
    SELECT round.id,
           COALESCE(SUM(snapshot.agent_daily_stake), 0) AS stake,
           COALESCE(SUM(snapshot.agent_daily_prize), 0) AS prize
    FROM competition_rounds round
    LEFT JOIN competition_daily_snapshots snapshot ON snapshot.round_id = round.id
    GROUP BY round.id
)
UPDATE competition_rounds round
SET agent_total_stake = totals.stake,
    agent_total_prize = totals.prize,
    agent_profit_loss = totals.prize - totals.stake,
    agent_roi = CASE
        WHEN totals.stake > 0 THEN (totals.prize - totals.stake) / totals.stake
        ELSE 0
    END,
    winner = CASE
        WHEN (CASE WHEN totals.stake > 0
                   THEN (totals.prize - totals.stake) / totals.stake ELSE 0 END)
             > COALESCE(round.user_roi, 0) THEN 'agent'
        WHEN (CASE WHEN totals.stake > 0
                   THEN (totals.prize - totals.stake) / totals.stake ELSE 0 END)
             < COALESCE(round.user_roi, 0) THEN 'user'
        ELSE 'draw'
    END,
    updated_at = NOW()
FROM round_totals totals
WHERE totals.id = round.id;

-- Database-level fail-closed guard: even a future direct insert cannot attach
-- an invalid prediction to an Agent ticket.
CREATE OR REPLACE FUNCTION enforce_valid_model_prediction_reference()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.model_prediction_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM model_predictions prediction
        WHERE prediction.id = NEW.model_prediction_id
          AND prediction.validation_status = 'valid'
    ) THEN
        RAISE EXCEPTION 'Agent ticket cannot reference invalid prediction %',
            NEW.model_prediction_id
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_simulation_ticket_prediction_valid
    ON simulation_ticket_items;

CREATE TRIGGER trg_simulation_ticket_prediction_valid
BEFORE INSERT OR UPDATE OF model_prediction_id ON simulation_ticket_items
FOR EACH ROW
EXECUTE FUNCTION enforce_valid_model_prediction_reference();

DROP TABLE invalid_budget_cleanup;
DROP TABLE invalid_ticket_cleanup;
DROP TABLE invalid_prediction_cleanup;
