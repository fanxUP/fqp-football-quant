-- 05_pool_reports_ops_schema.sql
CREATE TABLE IF NOT EXISTS football_pool_issues (
    id BIGSERIAL PRIMARY KEY,
    issue_no VARCHAR(64) NOT NULL UNIQUE,
    game_type VARCHAR(32) NOT NULL, -- sf14/rx9/bqc6/jq4
    sale_start_time TIMESTAMP,
    sale_stop_time TIMESTAMP,
    total_matches INT,
    official_status VARCHAR(32),
    prize_pool_estimate NUMERIC(14,2),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS football_pool_issue_matches (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES football_pool_issues(id),
    match_order INT NOT NULL,
    match_id BIGINT REFERENCES official_matches(id),
    league_name VARCHAR(128),
    home_team_name VARCHAR(128),
    away_team_name VARCHAR(128),
    kickoff_time TIMESTAMP,
    home_win_prob NUMERIC(10,6),
    draw_prob NUMERIC(10,6),
    away_win_prob NUMERIC(10,6),
    upset_score NUMERIC(10,6),
    public_heat_home NUMERIC(10,6),
    public_heat_draw NUMERIC(10,6),
    public_heat_away NUMERIC(10,6),
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(issue_id, match_order)
);

CREATE TABLE IF NOT EXISTS football_pool_combinations (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES football_pool_issues(id),
    strategy_name VARCHAR(128),
    combination_type VARCHAR(32),
    total_units INT,
    total_cost NUMERIC(12,2),
    estimated_hit_14_prob NUMERIC(10,8),
    estimated_hit_13_prob NUMERIC(10,8),
    expected_prize NUMERIC(14,2),
    expected_value NUMERIC(14,4),
    max_drawdown_risk NUMERIC(10,6),
    combination_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_reviews (
    id BIGSERIAL PRIMARY KEY,
    review_date DATE UNIQUE,
    official_match_count INT,
    analyzable_match_count INT,
    recommended_match_count INT,
    simulation_ticket_count INT,
    real_ticket_count INT,
    suggested_stake NUMERIC(12,2),
    actual_stake NUMERIC(12,2),
    simulation_prize NUMERIC(12,2),
    real_prize NUMERIC(12,2),
    simulation_profit_loss NUMERIC(12,2),
    real_profit_loss NUMERIC(12,2),
    simulation_roi NUMERIC(10,6),
    real_roi NUMERIC(10,6),
    budget_usage_rate NUMERIC(10,6),
    max_single_ticket_loss NUMERIC(12,2),
    max_single_match_exposure NUMERIC(12,2),
    summary_text TEXT,
    next_day_adjustment TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS weekly_reviews (
    id BIGSERIAL PRIMARY KEY,
    week_start DATE,
    week_end DATE,
    total_stake NUMERIC(12,2),
    total_prize NUMERIC(12,2),
    profit_loss NUMERIC(12,2),
    roi NUMERIC(10,6),
    max_drawdown NUMERIC(10,6),
    best_play_type VARCHAR(64),
    worst_play_type VARCHAR(64),
    best_league VARCHAR(128),
    worst_league VARCHAR(128),
    strategy_adjustment TEXT,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(week_start, week_end)
);

CREATE TABLE IF NOT EXISTS monthly_reviews (
    id BIGSERIAL PRIMARY KEY,
    month VARCHAR(7) UNIQUE,
    total_stake NUMERIC(12,2),
    total_prize NUMERIC(12,2),
    profit_loss NUMERIC(12,2),
    roi NUMERIC(10,6),
    max_drawdown NUMERIC(10,6),
    longest_losing_streak INT,
    best_strategy_pool VARCHAR(64),
    worst_strategy_pool VARCHAR(64),
    model_calibration_score NUMERIC(10,6),
    summary_text TEXT,
    next_month_plan TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prediction_error_analysis (
    id BIGSERIAL PRIMARY KEY,
    prediction_id BIGINT REFERENCES model_predictions(id),
    match_id BIGINT REFERENCES official_matches(id),
    error_type VARCHAR(128),
    error_level VARCHAR(32),
    root_cause TEXT,
    model_probability NUMERIC(10,6),
    market_probability NUMERIC(10,6),
    actual_result VARCHAR(64),
    suggested_fix TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    action_type VARCHAR(64),
    target_table VARCHAR(128),
    target_id BIGINT,
    before_json JSONB,
    after_json JSONB,
    ip_address VARCHAR(64),
    created_at TIMESTAMP DEFAULT now()
);
