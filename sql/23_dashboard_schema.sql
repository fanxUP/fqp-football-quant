-- 23_dashboard_schema.sql
-- Data Visualization Dashboard: aggregated views for frontend charts
-- Depends on: 01 (matches, odds), 03 (predictions), 04 (tickets, settlements),
--             19 (backtest), 21 (simulator), 22 (competition)
-- All views are idempotent (CREATE OR REPLACE VIEW)

-- =============================================================
-- 1. Today Summary — KPI data for homepage dashboard
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_today_summary AS
WITH today AS (
    SELECT CURRENT_DATE AS business_date
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
simulator_stats AS (
    SELECT
        COALESCE(SUM(st.total_cost), 0) AS sim_stake,
        COALESCE(SUM(st.bet_count), 0) AS sim_ticket_count
    FROM simulator_tickets st
    WHERE DATE(st.created_at) = (SELECT business_date FROM today)
),
settlement_stats AS (
    SELECT
        COUNT(*) FILTER (WHERE ts.ticket_source = 'simulation' AND ts.is_won = true) AS sim_won,
        COUNT(*) FILTER (WHERE ts.ticket_source = 'real' AND ts.is_won = true) AS real_won,
        COUNT(*) FILTER (WHERE ts.is_won IS NULL) AS pending_settlements,
        COALESCE(SUM(ts.profit_loss) FILTER (WHERE ts.ticket_source = 'simulation'), 0) AS ai_today_profit_loss,
        COALESCE(SUM(ts.profit_loss) FILTER (WHERE ts.ticket_source = 'real'), 0) AS real_today_profit_loss
    FROM ticket_settlements ts
    WHERE DATE(ts.settle_time) = (SELECT business_date FROM today)
),
current_round AS (
    SELECT id, round_label FROM competition_rounds
    WHERE status = 'active'
    LIMIT 1
)
SELECT
    (SELECT business_date FROM today) AS business_date,
    (SELECT total_matches FROM match_counts) AS match_count,
    (SELECT predicted_matches FROM prediction_counts) AS predicted_match_count,
    (SELECT total_predictions FROM prediction_counts) AS prediction_count,
    (SELECT sim_stake FROM simulator_stats) AS ai_stake_today,
    (SELECT sim_ticket_count FROM simulator_stats) AS ai_ticket_count,
    (SELECT pending_settlements FROM settlement_stats) AS pending_settlement_count,
    (SELECT ai_today_profit_loss FROM settlement_stats) AS ai_today_profit_loss,
    (SELECT real_today_profit_loss FROM settlement_stats) AS real_today_profit_loss,
    (SELECT round_label FROM current_round) AS current_round_label,
    (SELECT id FROM current_round) AS current_round_id;

-- =============================================================
-- 2. ROI Daily — daily competition data for ROI charts
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_roi_daily AS
SELECT
    cds.snapshot_date,
    cr.round_label,
    cr.id AS round_id,
    cds.agent_daily_stake,
    cds.agent_daily_prize,
    cds.agent_daily_profit_loss,
    CASE WHEN cds.agent_daily_stake > 0
         THEN cds.agent_daily_profit_loss / NULLIF(cds.agent_daily_stake, 0)
         ELSE NULL END AS agent_daily_roi,
    cds.agent_cumulative_roi,
    cds.agent_ticket_count,
    cds.user_daily_stake,
    cds.user_daily_prize,
    cds.user_daily_profit_loss,
    CASE WHEN cds.user_daily_stake > 0
         THEN cds.user_daily_profit_loss / NULLIF(cds.user_daily_stake, 0)
         ELSE NULL END AS user_daily_roi,
    cds.user_cumulative_roi,
    cds.user_ticket_count,
    -- Winner for this day (by daily ROI)
    CASE
        WHEN cds.agent_daily_stake > 0 AND cds.user_daily_stake > 0 THEN
            CASE
                WHEN cds.agent_daily_roi > cds.user_daily_roi THEN 'agent'
                WHEN cds.user_daily_roi > cds.agent_daily_roi THEN 'user'
                ELSE 'draw'
            END
        WHEN cds.agent_daily_stake > 0 AND (cds.user_daily_stake = 0 OR cds.user_daily_stake IS NULL) THEN 'agent_only'
        WHEN cds.user_daily_stake > 0 AND (cds.agent_daily_stake = 0 OR cds.agent_daily_stake IS NULL) THEN 'user_only'
        ELSE 'no_contest'
    END AS daily_winner
FROM competition_daily_snapshots cds
JOIN competition_rounds cr ON cr.id = cds.round_id
ORDER BY cds.snapshot_date DESC;

-- =============================================================
-- 3. ROI Period — round-level (weekly/monthly) summaries
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_roi_period AS
SELECT
    cr.id AS round_id,
    cr.round_label,
    cr.round_start,
    cr.round_end,
    cr.status,
    cr.agent_total_stake,
    cr.agent_total_prize,
    cr.agent_profit_loss,
    CASE WHEN cr.agent_total_stake > 0
         THEN cr.agent_profit_loss / NULLIF(cr.agent_total_stake, 0)
         ELSE NULL END AS agent_roi,
    cr.user_total_stake,
    cr.user_total_prize,
    cr.user_profit_loss,
    CASE WHEN cr.user_total_stake > 0
         THEN cr.user_profit_loss / NULLIF(cr.user_total_stake, 0)
         ELSE NULL END AS user_roi,
    cr.winner
FROM competition_rounds cr
ORDER BY cr.round_start DESC;

-- =============================================================
-- 4. Recommendation Summary — per-match prediction overview
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_recommendation_summary AS
SELECT
    mp.id AS prediction_id,
    m.business_date,
    m.id AS match_id,
    m.official_match_code,
    m.league_name,
    m.home_team_name,
    m.away_team_name,
    m.kickoff_time,
    mp.play_type,
    mp.option_code,
    mp.model_probability,
    mp.market_probability,
    mp.model_probability - mp.market_probability AS probability_edge,
    mp.ev,
    mp.fair_odds,
    mp.confidence_score,
    mp.risk_score,
    mv.model_name,
    mv.version AS model_version
FROM model_predictions mp
JOIN official_matches m ON m.id = mp.match_id
JOIN model_versions mv ON mv.id = mp.model_version_id
WHERE mp.ev IS NOT NULL
ORDER BY mp.ev DESC NULLS LAST;

-- =============================================================
-- 5. Odds Movement — SP time series for a match
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_odds_movement AS
SELECT
    oos.id AS snapshot_id,
    m.id AS match_id,
    m.official_match_code,
    m.home_team_name,
    m.away_team_name,
    m.league_name,
    oos.snapshot_time,
    oos.play_type,
    oos.option_code,
    oos.option_name,
    oos.sp_value,
    oos.handicap,
    -- Implied probability (1 / sp_value), no overround adjustment
    CASE WHEN oos.sp_value > 0 THEN 1.0 / oos.sp_value ELSE NULL END AS implied_probability,
    oos.minutes_before_stop,
    oos.is_open,
    -- Flag potential anomalies: sp > 50 (extremely long) or 10x previous snapshot
    LAG(oos.sp_value) OVER (
        PARTITION BY oos.match_id, oos.play_type, oos.option_code
        ORDER BY oos.snapshot_time
    ) AS prev_sp_value
FROM official_odds_snapshots oos
JOIN official_matches m ON m.id = oos.match_id
ORDER BY oos.match_id, oos.play_type, oos.option_code, oos.snapshot_time;

-- =============================================================
-- 6. Model Performance — per-model metrics across all predictions
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_model_performance AS
SELECT
    mv.id AS model_version_id,
    mv.model_name,
    mv.version,
    mv.model_type,
    COUNT(mem.id) AS sample_count,
    COUNT(mem.id) FILTER (WHERE mem.brier_score IS NOT NULL AND mem.brier_score <= 0.25) AS good_calibration_count,
    AVG(mem.brier_score) AS avg_brier_score,
    AVG(mem.log_loss) AS avg_log_loss,
    AVG(mem.ev) AS avg_ev,
    -- Aggregate backtest metrics if available
    brr.n_bets,
    brr.n_wins,
    brr.hit_rate,
    brr.roi,
    brr.total_profit,
    brr.sharpe_ratio,
    brr.max_drawdown_pct,
    brr.profit_factor
FROM model_versions mv
LEFT JOIN market_efficiency_metrics mem ON mem.model_version_id = mv.id
LEFT JOIN (
    SELECT DISTINCT ON (model_name)
        model_name, n_bets, n_wins, hit_rate, roi, total_profit,
        sharpe_ratio, max_drawdown_pct, profit_factor
    FROM backtest_run_results
    WHERE window_index IS NULL  -- aggregate rows only
    ORDER BY model_name, created_at DESC
) brr ON brr.model_name = mv.model_name
GROUP BY mv.id, mv.model_name, mv.version, mv.model_type,
         brr.n_bets, brr.n_wins, brr.hit_rate, brr.roi, brr.total_profit,
         brr.sharpe_ratio, brr.max_drawdown_pct, brr.profit_factor
ORDER BY mv.model_name, mv.version DESC;

-- =============================================================
-- 7. Backtest Equity Curve — per-window equity and drawdown
-- =============================================================
CREATE OR REPLACE VIEW v_dashboard_backtest_equity AS
SELECT
    br.id AS run_id,
    br.name AS run_name,
    br.status AS run_status,
    brw.window_index,
    brw.test_start_date,
    brw.test_end_date,
    brw.n_bets AS window_bets,
    brr.model_name,
    brr.n_bets,
    brr.n_wins,
    brr.hit_rate,
    brr.roi,
    brr.total_profit,
    brr.max_drawdown,
    brr.max_drawdown_pct,
    brr.sharpe_ratio,
    brr.profit_factor
FROM backtest_runs br
JOIN backtest_run_windows brw ON brw.run_id = br.id
JOIN backtest_run_results brr ON brr.run_id = br.id AND brr.window_index = brw.window_index
ORDER BY br.id DESC, brw.window_index;
