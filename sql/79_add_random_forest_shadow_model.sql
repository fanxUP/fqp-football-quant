-- 随机森林赛前特征模型：仅影子评估，不能参与推荐委员会或风控决策。

INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES (
    'random_forest_shadow',
    'random_forest_pre_match',
    '1.0.0',
    'Random forest trained on official pre-kickoff feature snapshots. Shadow mode only.',
    '{"rollout_mode":"shadow"}'::jsonb,
    true
)
ON CONFLICT (model_name, version) DO NOTHING;
