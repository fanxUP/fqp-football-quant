-- ============================================================
-- 18: Elo 动态评级系统
-- ============================================================
-- Elo 评分模型：基于比赛结果动态更新球队实力评分。
-- 特点：不依赖赔率数据，纯历史结果驱动，适合模型委员会投票。

BEGIN;

-- -------------------------------------------------------
-- 球队 Elo 评分表（历史追踪）
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_elo_ratings (
    id              BIGSERIAL PRIMARY KEY,
    team_id         INTEGER NOT NULL,
    team_name       VARCHAR(200),
    season          VARCHAR(20),            -- e.g. '2025-2026'
    elo_rating      DOUBLE PRECISION NOT NULL DEFAULT 1500.0,
    matches_played  INTEGER NOT NULL DEFAULT 0,
    peak_elo        DOUBLE PRECISION NOT NULL DEFAULT 1500.0,
    home_win_pct    DOUBLE PRECISION DEFAULT 0.0,
    away_win_pct    DOUBLE PRECISION DEFAULT 0.0,
    league_tier     VARCHAR(20) DEFAULT 'other',  -- 'top5', 'second', 'other'

    -- 追踪字段
    last_match_date DATE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 约束
    UNIQUE (team_id, season),
    FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_team_elo_rating
    ON team_elo_ratings (elo_rating DESC);
CREATE INDEX IF NOT EXISTS idx_team_elo_team_season
    ON team_elo_ratings (team_id, season);
CREATE INDEX IF NOT EXISTS idx_team_elo_season
    ON team_elo_ratings (season);


-- -------------------------------------------------------
-- Elo 更新日志表
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS elo_update_logs (
    id              BIGSERIAL PRIMARY KEY,
    match_id        INTEGER NOT NULL,
    home_team_id    INTEGER NOT NULL,
    away_team_id    INTEGER NOT NULL,

    -- 赛前评分
    home_elo_before DOUBLE PRECISION NOT NULL,
    away_elo_before DOUBLE PRECISION NOT NULL,

    -- 赛后评分
    home_elo_after  DOUBLE PRECISION NOT NULL,
    away_elo_after  DOUBLE PRECISION NOT NULL,

    -- 比赛详情
    home_goals      INTEGER NOT NULL,
    away_goals      INTEGER NOT NULL,
    result          VARCHAR(1) NOT NULL,    -- 'H', 'D', 'A'
    goal_diff       INTEGER NOT NULL,
    k_factor        DOUBLE PRECISION NOT NULL,
    elo_delta       DOUBLE PRECISION NOT NULL,  -- |Δhome| + |Δaway|

    -- 元数据
    season          VARCHAR(20),
    league_tier     VARCHAR(20),
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    FOREIGN KEY (match_id) REFERENCES official_matches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_elo_logs_match
    ON elo_update_logs (match_id);
CREATE INDEX IF NOT EXISTS idx_elo_logs_processed
    ON elo_update_logs (processed_at DESC);


-- -------------------------------------------------------
-- Elo 预测记录表（写入 model_predictions 表，
-- 此处仅增加 Elo 特定的 committee_vote weight 配置）
-- -------------------------------------------------------
-- 注：Elo 模型的预测结果写入已有的 model_predictions 和
-- model_committee_votes 表。此处不需要额外建表。

COMMIT;
