-- 04_recommendation_ticket_schema.sql
CREATE TABLE IF NOT EXISTS daily_budget_plans (
    id BIGSERIAL PRIMARY KEY,
    plan_date DATE NOT NULL UNIQUE,
    total_budget NUMERIC(12,2) DEFAULT 500,
    suggested_stake NUMERIC(12,2) DEFAULT 0,
    unused_budget NUMERIC(12,2) DEFAULT 0,
    risk_mode VARCHAR(32) DEFAULT 'balanced',
    reason TEXT,
    status VARCHAR(32) DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulation_tickets (
    id BIGSERIAL PRIMARY KEY,
    budget_plan_id BIGINT REFERENCES daily_budget_plans(id),
    strategy_pool VARCHAR(32) NOT NULL,
    ticket_type VARCHAR(32) NOT NULL,
    pass_type VARCHAR(32) NOT NULL,
    suggested_stake NUMERIC(12,2) NOT NULL,
    multiple INT DEFAULT 1,
    estimated_return NUMERIC(12,2),
    max_return NUMERIC(12,2),
    expected_value NUMERIC(12,4),
    risk_level VARCHAR(32),
    ticket_status VARCHAR(32) DEFAULT 'generated',
    invalid_reason TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulation_ticket_items (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES simulation_tickets(id),
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    odds_snapshot_id BIGINT REFERENCES official_odds_snapshots(id),
    model_prediction_id BIGINT REFERENCES model_predictions(id),
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    option_name VARCHAR(128) NOT NULL,
    sp_value NUMERIC(10,4) NOT NULL,
    model_probability NUMERIC(10,6),
    market_probability NUMERIC(10,6),
    ev NUMERIC(10,6),
    confidence_score NUMERIC(10,4),
    risk_score NUMERIC(10,4),
    is_dan BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bankroll_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    account_type VARCHAR(32) NOT NULL, -- simulation/real_ticket/experiment
    initial_balance NUMERIC(12,2) DEFAULT 0,
    current_balance NUMERIC(12,2) DEFAULT 0,
    daily_budget NUMERIC(12,2) DEFAULT 500,
    weekly_budget NUMERIC(12,2),
    monthly_budget NUMERIC(12,2),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bankroll_transactions (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES bankroll_accounts(id),
    transaction_type VARCHAR(32) NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    related_ticket_id BIGINT,
    balance_after NUMERIC(12,2),
    transaction_time TIMESTAMP DEFAULT now(),
    remark TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recommendation_shutdown_events (
    id BIGSERIAL PRIMARY KEY,
    event_date DATE NOT NULL,
    scope VARCHAR(32) NOT NULL, -- global/match/ticket
    match_id BIGINT,
    reason_code VARCHAR(128) NOT NULL,
    reason_text TEXT,
    severity VARCHAR(32) DEFAULT 'warning',
    is_blocking BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_tickets (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    related_simulation_ticket_id BIGINT REFERENCES simulation_tickets(id),
    ticket_image_url TEXT,
    ticket_no VARCHAR(128),
    purchase_time TIMESTAMP,
    store_code VARCHAR(128),
    total_amount NUMERIC(12,2),
    multiple INT,
    pass_type VARCHAR(64),
    theoretical_max_prize NUMERIC(12,2),
    source_type VARCHAR(32) DEFAULT 'user_upload',
    ocr_status VARCHAR(32) DEFAULT 'pending',
    confirm_status VARCHAR(32) DEFAULT 'pending',
    settlement_status VARCHAR(32) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_ticket_items (
    id BIGSERIAL PRIMARY KEY,
    real_ticket_id BIGINT NOT NULL REFERENCES real_tickets(id),
    match_id BIGINT REFERENCES official_matches(id),
    official_match_code VARCHAR(32),
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,
    option_name VARCHAR(128),
    sp_value NUMERIC(10,4),
    is_matched_with_model BOOLEAN DEFAULT false,
    deviation_type VARCHAR(64),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ticket_settlements (
    id BIGSERIAL PRIMARY KEY,
    ticket_source VARCHAR(32) NOT NULL, -- simulation/real
    ticket_id BIGINT NOT NULL,
    settle_time TIMESTAMP DEFAULT now(),
    is_won BOOLEAN,
    stake_amount NUMERIC(12,2),
    prize_amount NUMERIC(12,2),
    tax_amount NUMERIC(12,2) DEFAULT 0,
    net_prize NUMERIC(12,2),
    profit_loss NUMERIC(12,2),
    roi NUMERIC(10,6),
    settlement_detail_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);
