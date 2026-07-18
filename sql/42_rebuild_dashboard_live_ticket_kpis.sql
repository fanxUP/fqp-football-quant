-- Align the homepage Agent KPIs with the unified betting ledger contract.
-- Agent capital is committed when a valid simulation ticket is created;
-- pending tickets do not exist in ticket_settlements yet.
CREATE OR REPLACE VIEW v_dashboard_today_summary AS
WITH today AS (
    SELECT timezone('Asia/Shanghai', NOW())::date AS business_date
),
match_counts AS (
    SELECT COUNT(*) AS total_matches
    FROM official_matches m
    WHERE m.business_date = (SELECT business_date FROM today)
      AND m.sale_status = 'selling'
),
prediction_counts AS (
    SELECT COUNT(DISTINCT mp.match_id) AS predicted_matches,
           COUNT(*) AS total_predictions
    FROM model_predictions mp
    JOIN official_matches m ON m.id = mp.match_id
    WHERE m.business_date = (SELECT business_date FROM today)
),
agent_ticket_stats AS (
    SELECT
        COALESCE(SUM(st.suggested_stake), 0) AS agent_stake,
        COUNT(*) AS agent_ticket_count
    FROM simulation_tickets st
    WHERE (st.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
              = (SELECT business_date FROM today)
      AND st.ticket_status <> 'cancelled'
      AND EXISTS (
          SELECT 1
          FROM simulation_ticket_items sti
          WHERE sti.ticket_id = st.id
      )
),
agent_pending_stats AS (
    SELECT COUNT(*) AS pending_ticket_count
    FROM simulation_tickets st
    WHERE st.ticket_status NOT IN ('settled', 'cancelled')
      AND EXISTS (
          SELECT 1
          FROM simulation_ticket_items sti
          WHERE sti.ticket_id = st.id
      )
),
settlement_stats AS (
    SELECT
        COALESCE(SUM(ts.stake_amount) FILTER (
            WHERE ts.ticket_source = 'simulation'
        ), 0) AS ai_settled_stake_today,
        COALESCE(SUM(ts.profit_loss) FILTER (
            WHERE ts.ticket_source = 'simulation'
        ), 0) AS ai_today_profit_loss,
        COALESCE(SUM(ts.profit_loss) FILTER (
            WHERE ts.ticket_source = 'real'
        ), 0) AS real_today_profit_loss
    FROM ticket_settlements ts
    WHERE (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
              = (SELECT business_date FROM today)
),
current_round AS (
    SELECT id, round_label
    FROM competition_rounds
    WHERE status = 'active'
    ORDER BY round_start DESC, id DESC
    LIMIT 1
)
SELECT
    (SELECT business_date FROM today) AS business_date,
    (SELECT total_matches FROM match_counts) AS match_count,
    (SELECT predicted_matches FROM prediction_counts) AS predicted_match_count,
    (SELECT total_predictions FROM prediction_counts) AS prediction_count,
    (SELECT agent_stake FROM agent_ticket_stats) AS ai_stake_today,
    (SELECT agent_ticket_count FROM agent_ticket_stats) AS ai_ticket_count,
    (SELECT pending_ticket_count FROM agent_pending_stats) AS pending_settlement_count,
    (SELECT ai_settled_stake_today FROM settlement_stats) AS ai_settled_stake_today,
    (SELECT ai_today_profit_loss FROM settlement_stats) AS ai_today_profit_loss,
    (SELECT real_today_profit_loss FROM settlement_stats) AS real_today_profit_loss,
    (SELECT round_label FROM current_round) AS current_round_label,
    (SELECT id FROM current_round) AS current_round_id;
