-- Repair older local databases whose simulation ticket tables predate the
-- betting-center runtime contract. All additions are backward compatible.
ALTER TABLE simulation_tickets
    ADD COLUMN IF NOT EXISTS bet_count INT NOT NULL DEFAULT 1;

ALTER TABLE simulation_tickets
    ADD COLUMN IF NOT EXISTS rule_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE simulation_ticket_items
    ADD COLUMN IF NOT EXISTS odds_source VARCHAR(32) NOT NULL DEFAULT 'official';
