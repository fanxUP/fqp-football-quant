-- FQP local single-user and UI/module runtime schema

CREATE TABLE IF NOT EXISTS local_operator_profile (
    id BIGSERIAL PRIMARY KEY,
    operator_code VARCHAR(64) NOT NULL UNIQUE DEFAULT 'owner',
    display_name VARCHAR(128) NOT NULL DEFAULT '本地用户',
    auth_mode VARCHAR(32) NOT NULL DEFAULT 'none',
    pin_hash TEXT,
    daily_budget NUMERIC(12,2) NOT NULL DEFAULT 500,
    risk_mode VARCHAR(32) NOT NULL DEFAULT 'balanced',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS local_app_settings (
    id BIGSERIAL PRIMARY KEY,
    setting_key VARCHAR(128) NOT NULL UNIQUE,
    setting_value JSONB NOT NULL,
    setting_group VARCHAR(64),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime_modules (
    id BIGSERIAL PRIMARY KEY,
    module_id VARCHAR(128) NOT NULL UNIQUE,
    module_name VARCHAR(128) NOT NULL,
    module_category VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(32) NOT NULL DEFAULT 'enabled',
    required BOOLEAN DEFAULT false,
    safe_disable BOOLEAN DEFAULT true,
    safe_remove BOOLEAN DEFAULT false,
    dependencies JSONB DEFAULT '[]'::jsonb,
    config_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime_panels (
    id BIGSERIAL PRIMARY KEY,
    panel_id VARCHAR(128) NOT NULL UNIQUE,
    module_id VARCHAR(128) NOT NULL,
    panel_name VARCHAR(128) NOT NULL,
    route_path VARCHAR(256) NOT NULL,
    visible BOOLEAN DEFAULT true,
    sort_order INT DEFAULT 100,
    icon VARCHAR(64),
    theme_id VARCHAR(64) DEFAULT 'red_black_tech',
    config_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS local_ui_theme_settings (
    id BIGSERIAL PRIMARY KEY,
    theme_id VARCHAR(64) NOT NULL UNIQUE,
    theme_name VARCHAR(128) NOT NULL,
    color_tokens JSONB NOT NULL,
    component_tokens JSONB NOT NULL,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS module_change_log (
    id BIGSERIAL PRIMARY KEY,
    module_id VARCHAR(128) NOT NULL,
    action VARCHAR(64) NOT NULL,
    before_state JSONB,
    after_state JSONB,
    reason TEXT,
    requires_backup BOOLEAN DEFAULT true,
    backup_path TEXT,
    created_at TIMESTAMP DEFAULT now()
);

INSERT INTO local_operator_profile (operator_code, display_name, auth_mode, daily_budget, risk_mode)
VALUES ('owner', '本地用户', 'none', 500, 'balanced')
ON CONFLICT (operator_code) DO NOTHING;
