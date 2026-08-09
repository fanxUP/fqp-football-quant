INSERT INTO model_versions (model_name, model_type, version, description, parameters_json, is_active)
VALUES ('mlp_shadow','mlp_pre_match','1.0.0','MLP pre-match classifier with chronological holdout. Shadow mode only.','{"rollout_mode":"shadow"}'::jsonb,true)
ON CONFLICT (model_name, version) DO NOTHING;
