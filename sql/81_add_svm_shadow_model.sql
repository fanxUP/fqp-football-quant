-- RBF 支持向量机赛前模型：仅影子评估，不能参与推荐委员会或风控决策。
INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES ('svm_shadow', 'rbf_svm_pre_match', '1.0.0', 'RBF SVM on official pre-kickoff features. Shadow mode only.', '{"rollout_mode":"shadow"}'::jsonb, true)
ON CONFLICT (model_name, version) DO NOTHING;
