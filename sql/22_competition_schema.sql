-- 22_competition_schema.sql
-- 双资金池对抗竞赛：Agent（虚拟¥500/天）vs 用户（实票金额），按ROI判定胜负
-- 复用 bankroll_accounts（account_type = 'competition_agent'）
-- 复用 ticket_settlements（ticket_source = 'simulation' / 'real'）

CREATE TABLE IF NOT EXISTS competition_rounds (
    id BIGSERIAL PRIMARY KEY,
    round_label VARCHAR(64) NOT NULL,          -- e.g., "2026-W27"
    round_start DATE NOT NULL,                  -- Monday
    round_end DATE NOT NULL,                    -- Sunday
    -- Agent pool (simulation_tickets → ticket_settlements where ticket_source='simulation')
    agent_total_stake NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_total_prize NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_profit_loss NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_roi NUMERIC(10,6) NOT NULL DEFAULT 0,
    -- User pool (real_tickets → ticket_settlements where ticket_source='real')
    user_total_stake NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_total_prize NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_profit_loss NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_roi NUMERIC(10,6) NOT NULL DEFAULT 0,
    -- Result
    winner VARCHAR(16),                         -- 'agent' | 'user' | 'draw'
    status VARCHAR(16) NOT NULL DEFAULT 'active',  -- 'active' | 'completed'
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (round_start, round_end)
);

CREATE TABLE IF NOT EXISTS competition_daily_snapshots (
    id BIGSERIAL PRIMARY KEY,
    round_id BIGINT NOT NULL REFERENCES competition_rounds(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    -- Agent pool (simulation tickets)
    agent_daily_stake NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_daily_prize NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_daily_profit_loss NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_daily_roi NUMERIC(10,6) NOT NULL DEFAULT 0,
    agent_cumulative_stake NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_cumulative_prize NUMERIC(12,2) NOT NULL DEFAULT 0,
    agent_cumulative_roi NUMERIC(10,6) NOT NULL DEFAULT 0,
    agent_budget_usage_rate NUMERIC(10,4) NOT NULL DEFAULT 0,   -- % of ¥500 used
    agent_ticket_count INT NOT NULL DEFAULT 0,
    -- User pool (real tickets)
    user_daily_stake NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_daily_prize NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_daily_profit_loss NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_daily_roi NUMERIC(10,6) NOT NULL DEFAULT 0,
    user_cumulative_stake NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_cumulative_prize NUMERIC(12,2) NOT NULL DEFAULT 0,
    user_cumulative_roi NUMERIC(10,6) NOT NULL DEFAULT 0,
    user_ticket_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (round_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_comp_rounds_status ON competition_rounds(status);
CREATE INDEX IF NOT EXISTS idx_comp_rounds_label ON competition_rounds(round_label);
CREATE INDEX IF NOT EXISTS idx_comp_snapshots_date ON competition_daily_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_comp_snapshots_round ON competition_daily_snapshots(round_id);
