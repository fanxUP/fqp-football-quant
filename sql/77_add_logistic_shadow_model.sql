-- 正则化逻辑回归赛前特征模型：仅影子评估，不能参与推荐委员会或风控决策。

INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES (
    'logistic_shadow',
    'prematch_feature_classifier',
    '1.0.0',
    'Regularized logistic pre-match feature classifier with chronological holdout validation. Shadow mode only.',
    '{"rollout_mode":"shadow"}'::jsonb,
    true
)
ON CONFLICT (model_name, version) DO NOTHING;
