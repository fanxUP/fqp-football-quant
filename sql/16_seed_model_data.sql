-- 16_seed_model_data.sql
-- Seed data for Stage 4: model versions, budget plans, bankroll accounts.
-- Idempotent — uses ON CONFLICT DO NOTHING for all inserts.

-- -------------------------------------------------------------------
-- Model versions (from configs/model_registry.yaml)
-- -------------------------------------------------------------------
INSERT INTO model_versions (model_name, model_type, version, description, is_active)
VALUES
    ('market_baseline', 'market_probability', '1.0.0',
     'Odds-implied probability via normalization (removes overround). Baseline all models must beat.',
     true),
    ('maher_poisson', 'score_distribution', '1.0.0',
     'Maher (1982) independent Poisson model. Lambdas reverse-engineered from Shin-debiased odds.',
     false),
    ('dixon_coles', 'low_score_adjustment', '1.0.0',
     'Dixon-Coles (1997) low-score correction with fixed rho=-0.08. Requires historical data for proper MLE.',
     false),
    ('elo_rating', 'dynamic_strength_rating', '1.0.0',
     'Elo (1978) dynamic rating model. Pure historical strength — no odds dependency. Votes in model committee.',
     false)
ON CONFLICT (model_name, version) DO NOTHING;

-- -------------------------------------------------------------------
-- Daily budget plan (from configs/bankroll_rules.yaml)
-- 500 CNY total, 4 strategy pools
-- -------------------------------------------------------------------
INSERT INTO daily_budget_plans (plan_date, total_budget, unused_budget, risk_mode, status)
VALUES (
    CURRENT_DATE,
    500,
    500,
    'balanced',
    'active'
)
ON CONFLICT (plan_date) DO NOTHING;

-- -------------------------------------------------------------------
-- Bankroll account (simulation mode)
-- -------------------------------------------------------------------
INSERT INTO bankroll_accounts (user_id, account_type, initial_balance, current_balance, daily_budget)
VALUES (
    1,
    'simulation',
    500,
    500,
    500
)
ON CONFLICT DO NOTHING;
