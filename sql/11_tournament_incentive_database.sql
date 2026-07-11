-- 11_tournament_incentive_database.sql
-- 战意、晋级、避强队、赛制博弈数据库

CREATE TABLE IF NOT EXISTS team_motivation_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_season_id BIGINT REFERENCES competition_seasons(id),
    snapshot_time TIMESTAMP NOT NULL,
    current_rank INT,
    current_points INT,
    remaining_matches INT,
    title_race_score NUMERIC(10,4),
    continental_race_score NUMERIC(10,4),
    promotion_score NUMERIC(10,4),
    relegation_pressure_score NUMERIC(10,4),
    mid_table_no_pressure_score NUMERIC(10,4),
    must_win BOOLEAN DEFAULT false,
    draw_enough BOOLEAN DEFAULT false,
    already_qualified BOOLEAN DEFAULT false,
    already_eliminated BOOLEAN DEFAULT false,
    need_goal_difference BOOLEAN DEFAULT false,
    derby_motivation_score NUMERIC(10,4),
    revenge_motivation_score NUMERIC(10,4),
    manager_pressure_score NUMERIC(10,4),
    final_motivation_score NUMERIC(10,4),
    motivation_reason JSONB,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tournament_group_scenarios (
    id BIGSERIAL PRIMARY KEY,
    competition_season_id BIGINT NOT NULL REFERENCES competition_seasons(id),
    group_code VARCHAR(32),
    snapshot_time TIMESTAMP NOT NULL,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    current_points INT,
    current_goal_difference INT,
    current_goals_for INT,
    qualify_probability NUMERIC(10,6),
    first_place_probability NUMERIC(10,6),
    second_place_probability NUMERIC(10,6),
    elimination_probability NUMERIC(10,6),
    draw_is_enough BOOLEAN,
    win_required BOOLEAN,
    goal_difference_target INT,
    scenario_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tournament_incentive_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    snapshot_time TIMESTAMP NOT NULL,
    current_group_rank INT,
    qualification_status VARCHAR(32),
    potential_rank_if_win INT,
    potential_rank_if_draw INT,
    potential_rank_if_loss INT,
    potential_opponents_if_win JSONB,
    potential_opponents_if_draw JSONB,
    potential_opponents_if_loss JSONB,
    bracket_difficulty_if_win NUMERIC(10,4),
    bracket_difficulty_if_draw NUMERIC(10,4),
    bracket_difficulty_if_loss NUMERIC(10,4),
    avoid_strong_opponent_score NUMERIC(10,4),
    tanking_risk_score NUMERIC(10,4),
    rotation_after_qualification_score NUMERIC(10,4),
    incentive_summary TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_motivation_match_team_snap ON team_motivation_snapshots(match_id, team_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_group_scenarios_comp_group_snap ON tournament_group_scenarios(competition_season_id, group_code, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_incentive_match_team_snap ON tournament_incentive_snapshots(match_id, team_id, snapshot_time);
