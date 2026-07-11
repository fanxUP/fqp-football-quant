-- 19_backtest_schema.sql
-- Backtest Center: walk-forward validation, equity curve, metrics aggregation.
-- Stores backtest run configuration, window splits, and per-model results.

-- -------------------------------------------------------------------
-- Backtest runs — one row per backtest execution
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_runs (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    config          JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','cancelled')),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------------
-- Walk-forward windows — one row per (run, window_index)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_run_windows (
    id                BIGSERIAL PRIMARY KEY,
    run_id            BIGINT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    window_index      INT NOT NULL,
    train_start_date  DATE,
    train_end_date    DATE,
    test_start_date   DATE NOT NULL,
    test_end_date     DATE NOT NULL,
    n_train_matches   INT NOT NULL DEFAULT 0,
    n_test_matches    INT NOT NULL DEFAULT 0,
    n_bets            INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bt_windows_run ON backtest_run_windows(run_id);

-- -------------------------------------------------------------------
-- Backtest results — per-model metrics, one row per (run, window, model)
-- window_index IS NULL → aggregate across all windows
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_run_results (
    id                    BIGSERIAL PRIMARY KEY,
    run_id                BIGINT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    window_index          INT,            -- NULL = aggregate summary
    model_name            VARCHAR(128) NOT NULL,
    n_bets                INT NOT NULL DEFAULT 0,
    n_wins                INT NOT NULL DEFAULT 0,
    hit_rate              NUMERIC(7,4),
    roi                   NUMERIC(7,4),  -- decimal, e.g. 0.0523 = 5.23%
    total_profit          NUMERIC(12,4),  -- total P&L in units
    avg_odds              NUMERIC(7,4),
    brier_score           NUMERIC(7,4),
    log_loss              NUMERIC(7,4),
    clv                   NUMERIC(7,4),  -- average Closing Line Value
    max_drawdown          NUMERIC(12,4), -- maximum drawdown in units
    max_drawdown_pct      NUMERIC(7,4),  -- maximum drawdown as percentage
    longest_losing_streak INT NOT NULL DEFAULT 0,
    sharpe_ratio          NUMERIC(7,4),
    profit_factor         NUMERIC(7,4),  -- gross_profit / |gross_loss|
    equity_curve          JSONB,         -- [{date, bankroll, drawdown_pct}, ...]
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bt_results_run ON backtest_run_results(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_results_model ON backtest_run_results(model_name);
