-- 极端随机树赛前特征模型：仅影子评估，绝不进入推荐、投注或风控决策。
INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES ('extra_trees_shadow', 'extra_trees_pre_match', '1.0.0',
        'Extra-trees pre-match feature classifier with chronological holdout. Shadow mode only.',
        '{"rollout_mode":"shadow"}'::jsonb, true)
ON CONFLICT (model_name, version) DO NOTHING;
