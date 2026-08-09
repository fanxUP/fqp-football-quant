-- 高斯朴素贝叶斯赛前模型：仅影子评估，不能参与推荐委员会或风控决策。
INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES ('naive_bayes_shadow', 'gaussian_naive_bayes_pre_match', '1.0.0',
        'Gaussian naive Bayes on official pre-kickoff feature snapshots. Shadow mode only.',
        '{"rollout_mode":"shadow"}'::jsonb, true)
ON CONFLICT (model_name, version) DO NOTHING;
