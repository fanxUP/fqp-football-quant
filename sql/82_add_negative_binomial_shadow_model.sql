-- 负二项进球分布：仅影子评估，绝不进入推荐、投注或风控决策。
INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES ('negative_binomial_shadow', 'overdispersed_score_distribution', '1.0.0',
        'Negative-binomial score distribution fitted from official settled goals. Shadow mode only.',
        '{"rollout_mode":"shadow"}'::jsonb, true)
ON CONFLICT (model_name, version) DO NOTHING;
