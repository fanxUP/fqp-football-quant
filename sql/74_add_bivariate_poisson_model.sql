-- 双变量泊松：以共享进球成分表达双方比分相关性，初始仅影子验证。

INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES (
    'bivariate_poisson',
    'correlated_score_distribution',
    '1.0.0',
    'Bivariate Poisson score distribution with a fitted shared-goal component. Starts in shadow mode until evaluation gates pass.',
    '{"rollout_mode":"shadow"}'::jsonb,
    true
)
ON CONFLICT (model_name, version) DO NOTHING;
