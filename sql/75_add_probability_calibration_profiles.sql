-- 独立保存概率校准的影子评估资料；绝不改写原始预测事实。
CREATE TABLE IF NOT EXISTS probability_calibration_profiles (
    id BIGSERIAL PRIMARY KEY,
    model_name VARCHAR(128) NOT NULL,
    play_type VARCHAR(32) NOT NULL,
    method_name VARCHAR(64) NOT NULL,
    calibration_version VARCHAR(64) NOT NULL,
    parameters_json JSONB NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count > 0),
    log_loss_before NUMERIC(12, 6) NOT NULL,
    log_loss_after NUMERIC(12, 6) NOT NULL,
    training_end_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (model_name, play_type, calibration_version)
);

CREATE INDEX IF NOT EXISTS idx_probability_calibration_profiles_active
    ON probability_calibration_profiles (model_name, play_type, is_active, created_at DESC);

GRANT SELECT, INSERT, UPDATE ON probability_calibration_profiles TO fqp;
GRANT USAGE, SELECT ON SEQUENCE probability_calibration_profiles_id_seq TO fqp;
