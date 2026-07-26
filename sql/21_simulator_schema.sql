-- 21_simulator_schema.sql
-- 体彩官方投注模拟器：虚拟投注票单、投注项
-- 复用 bankroll_accounts / bankroll_transactions（account_type = 'simulator'）
-- 复用 ticket_settlements（ticket_source = 'simulator'）

CREATE TABLE IF NOT EXISTS simulator_tickets (
    id BIGSERIAL PRIMARY KEY,
    play_type VARCHAR(32) NOT NULL DEFAULT 'spf',  -- spf / rqspf / zjq / bf / bqc / hhgg
    pass_type VARCHAR(64) NOT NULL DEFAULT 'single', -- single / 2x1 / 3x3 / 4x11 ...
    multiple INT NOT NULL DEFAULT 1,
    total_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    bet_count INT NOT NULL DEFAULT 1,
    max_prize NUMERIC(12,2) DEFAULT 0,
    match_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending / settled / cancelled
    notes TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulator_ticket_items (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES simulator_tickets(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    play_type VARCHAR(32) NOT NULL,
    option_code VARCHAR(64) NOT NULL,   -- 3/1/0 for SPF; 1:0/2:1 for score; 33/31 for half/full
    option_name VARCHAR(128) NOT NULL,
    sp_value NUMERIC(10,4) NOT NULL CHECK (sp_value > 0),
    handicap NUMERIC(5,1),              -- for RQSPF
    is_dan BOOLEAN DEFAULT false,       -- banker match (v2 feature)
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sim_tickets_status ON simulator_tickets(status);
CREATE INDEX IF NOT EXISTS idx_sim_tickets_created ON simulator_tickets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sim_ticket_items_ticket ON simulator_ticket_items(ticket_id);
CREATE INDEX IF NOT EXISTS idx_sim_ticket_items_match ON simulator_ticket_items(match_id);
