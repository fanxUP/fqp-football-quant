-- 时光机补录：保存每个选项对应的体彩封盘前赔率证据。
ALTER TABLE real_ticket_items
    ADD COLUMN IF NOT EXISTS odds_snapshot_id BIGINT REFERENCES official_odds_snapshots(id),
    ADD COLUMN IF NOT EXISTS odds_snapshot_time TIMESTAMP,
    ADD COLUMN IF NOT EXISTS odds_source VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_real_ticket_items_odds_snapshot
    ON real_ticket_items (odds_snapshot_id)
    WHERE odds_snapshot_id IS NOT NULL;
