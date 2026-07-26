-- 12_match_feature_snapshots.sql
-- 比赛多维特征快照总表，用于模型训练、推荐绑定和赛后回测

CREATE TABLE IF NOT EXISTS match_feature_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL,
    snapshot_time TIMESTAMP NOT NULL,
    feature_version VARCHAR(64) NOT NULL,
    home_team_id BIGINT NOT NULL REFERENCES teams(id),
    away_team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_season_id BIGINT REFERENCES competition_seasons(id),

    -- 球队赛季实力
    home_team_market_value NUMERIC(16,2),
    away_team_market_value NUMERIC(16,2),
    team_market_value_diff NUMERIC(16,2),
    team_market_value_ratio NUMERIC(10,6),
    home_attack_strength_score NUMERIC(10,4),
    away_attack_strength_score NUMERIC(10,4),
    home_defense_strength_score NUMERIC(10,4),
    away_defense_strength_score NUMERIC(10,4),

    -- 首发阵容
    home_lineup_confirmed BOOLEAN,
    away_lineup_confirmed BOOLEAN,
    home_starting_11_value NUMERIC(16,2),
    away_starting_11_value NUMERIC(16,2),
    starting_11_value_diff NUMERIC(16,2),
    home_lineup_strength_score NUMERIC(10,4),
    away_lineup_strength_score NUMERIC(10,4),
    lineup_strength_diff NUMERIC(10,4),

    -- 伤停
    home_absence_impact_score NUMERIC(10,4),
    away_absence_impact_score NUMERIC(10,4),
    absence_impact_diff NUMERIC(10,4),
    home_key_absence_count INT,
    away_key_absence_count INT,

    -- 轮换与赛程
    home_rotation_risk_score NUMERIC(10,4),
    away_rotation_risk_score NUMERIC(10,4),
    rotation_risk_diff NUMERIC(10,4),
    home_rest_days INT,
    away_rest_days INT,
    rest_days_diff INT,

    -- 旅行与地理
    stadium_id BIGINT REFERENCES stadiums(id),
    away_travel_distance_km NUMERIC(10,2),
    timezone_diff NUMERIC(5,2),
    altitude_m NUMERIC(10,2),
    away_travel_fatigue_score NUMERIC(10,4),

    -- 天气
    temperature_2m NUMERIC(8,2),
    precipitation NUMERIC(8,2),
    wind_speed_10m NUMERIC(8,2),
    weather_impact_score NUMERIC(10,4),
    goal_expectation_weather_adjustment NUMERIC(10,6),

    -- 战意
    home_motivation_score NUMERIC(10,4),
    away_motivation_score NUMERIC(10,4),
    motivation_diff NUMERIC(10,4),
    home_must_win BOOLEAN,
    away_must_win BOOLEAN,
    home_draw_enough BOOLEAN,
    away_draw_enough BOOLEAN,

    -- 赛制博弈
    home_avoid_strong_opponent_score NUMERIC(10,4),
    away_avoid_strong_opponent_score NUMERIC(10,4),
    home_tanking_risk_score NUMERIC(10,4),
    away_tanking_risk_score NUMERIC(10,4),
    tournament_incentive_risk_score NUMERIC(10,4),

    -- 数据质量
    data_completeness_score NUMERIC(10,4),
    source_confidence_score NUMERIC(10,4),
    uncertainty_score NUMERIC(10,4),

    raw_feature_refs JSONB,
    created_at TIMESTAMP DEFAULT now()
);

-- 推荐预测表建议增加特征快照外键，若原表已存在则安全新增。
ALTER TABLE model_predictions
    ADD COLUMN IF NOT EXISTS feature_snapshot_id BIGINT REFERENCES match_feature_snapshots(id);

ALTER TABLE simulation_ticket_items
    ADD COLUMN IF NOT EXISTS feature_snapshot_id BIGINT REFERENCES match_feature_snapshots(id);

CREATE INDEX IF NOT EXISTS idx_match_feature_match_snap ON match_feature_snapshots(match_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_match_feature_teams ON match_feature_snapshots(home_team_id, away_team_id);
CREATE INDEX IF NOT EXISTS idx_match_feature_quality ON match_feature_snapshots(data_completeness_score);
