-- FQP 模块化与功能面板扩展 schema

CREATE TABLE IF NOT EXISTS system_modules (
    id BIGSERIAL PRIMARY KEY,
    module_code VARCHAR(128) NOT NULL UNIQUE,
    module_name VARCHAR(128) NOT NULL,
    module_category VARCHAR(64) NOT NULL,
    module_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    schema_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    api_version VARCHAR(32) NOT NULL DEFAULT 'v1',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    is_core BOOLEAN DEFAULT false,
    owner_agent VARCHAR(128),
    description TEXT,
    manifest_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS module_dependencies (
    id BIGSERIAL PRIMARY KEY,
    module_code VARCHAR(128) NOT NULL REFERENCES system_modules(module_code),
    depends_on_module_code VARCHAR(128) NOT NULL REFERENCES system_modules(module_code),
    dependency_type VARCHAR(32) NOT NULL DEFAULT 'runtime',
    min_version VARCHAR(32),
    is_required BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE (module_code, depends_on_module_code)
);

CREATE TABLE IF NOT EXISTS feature_flags (
    id BIGSERIAL PRIMARY KEY,
    flag_key VARCHAR(128) NOT NULL UNIQUE,
    module_code VARCHAR(128) REFERENCES system_modules(module_code),
    flag_name VARCHAR(128),
    is_enabled BOOLEAN DEFAULT false,
    environment VARCHAR(32) DEFAULT 'production',
    rollout_percentage NUMERIC(6,2) DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS frontend_panels (
    id BIGSERIAL PRIMARY KEY,
    panel_code VARCHAR(128) NOT NULL UNIQUE,
    module_code VARCHAR(128) NOT NULL REFERENCES system_modules(module_code),
    panel_name VARCHAR(128) NOT NULL,
    panel_type VARCHAR(32) NOT NULL,
    route_path VARCHAR(256) NOT NULL,
    component_name VARCHAR(128) NOT NULL,
    menu_group VARCHAR(64),
    icon_name VARCHAR(64),
    display_order INT DEFAULT 100,
    status VARCHAR(32) DEFAULT 'active',
    required_permissions JSONB,
    feature_flags JSONB,
    panel_config JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS module_permissions (
    id BIGSERIAL PRIMARY KEY,
    permission_code VARCHAR(128) NOT NULL UNIQUE,
    module_code VARCHAR(128) NOT NULL REFERENCES system_modules(module_code),
    permission_name VARCHAR(128) NOT NULL,
    action VARCHAR(64) NOT NULL,
    scope VARCHAR(64) NOT NULL,
    risk_level VARCHAR(32) DEFAULT 'normal',
    description TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plugin_registry (
    id BIGSERIAL PRIMARY KEY,
    plugin_code VARCHAR(128) NOT NULL UNIQUE,
    plugin_name VARCHAR(128) NOT NULL,
    plugin_type VARCHAR(64) NOT NULL,
    module_code VARCHAR(128) NOT NULL REFERENCES system_modules(module_code),
    plugin_version VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'registered',
    entrypoint TEXT,
    config_json JSONB,
    rollback_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS module_upgrade_logs (
    id BIGSERIAL PRIMARY KEY,
    module_code VARCHAR(128) NOT NULL,
    from_version VARCHAR(32),
    to_version VARCHAR(32),
    upgrade_type VARCHAR(32),
    codex_task_id BIGINT,
    migration_files JSONB,
    test_result_json JSONB,
    review_status VARCHAR(32),
    rollback_plan TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_frontend_panels_module ON frontend_panels(module_code);
CREATE INDEX IF NOT EXISTS idx_feature_flags_module ON feature_flags(module_code);
CREATE INDEX IF NOT EXISTS idx_module_permissions_module ON module_permissions(module_code);
CREATE INDEX IF NOT EXISTS idx_plugin_registry_module ON plugin_registry(module_code);
