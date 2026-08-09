-- 贝叶斯近期状态模型：仅影子评估，不能参与推荐委员会或风控决策。

INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES (
    'bayesian_form',
    'bayesian_recent_form',
    '1.0.0',
    'Dirichlet-smoothed recent-form model from official settled results before kickoff. Shadow mode only.',
    '{"rollout_mode":"shadow"}'::jsonb,
    true
)
ON CONFLICT (model_name, version) DO NOTHING;
