-- 06_indexes_constraints.sql
CREATE INDEX IF NOT EXISTS idx_official_matches_date ON official_matches(business_date);
CREATE INDEX IF NOT EXISTS idx_official_matches_code ON official_matches(official_match_code);
CREATE INDEX IF NOT EXISTS idx_odds_match_time ON official_odds_snapshots(match_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_odds_play_option ON official_odds_snapshots(play_type, option_code);
CREATE INDEX IF NOT EXISTS idx_predictions_match ON model_predictions(match_id, play_type, option_code);
CREATE INDEX IF NOT EXISTS idx_predictions_model ON model_predictions(model_version_id);
CREATE INDEX IF NOT EXISTS idx_sim_ticket_budget ON simulation_tickets(budget_plan_id);
CREATE INDEX IF NOT EXISTS idx_real_ticket_date ON real_tickets(purchase_time);
CREATE INDEX IF NOT EXISTS idx_pool_issue ON football_pool_issue_matches(issue_id, match_order);
CREATE INDEX IF NOT EXISTS idx_reviews_daily ON daily_reviews(review_date);
