-- FQP Multi-Agent & Codex orchestration schema

CREATE TABLE IF NOT EXISTS agent_registry (
    id BIGSERIAL PRIMARY KEY,
    agent_name VARCHAR(128) NOT NULL UNIQUE,
    agent_type VARCHAR(64) NOT NULL,
    description TEXT,
    permission_level VARCHAR(32) NOT NULL,
    allowed_actions JSONB,
    forbidden_actions JSONB,
    owner VARCHAR(128),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_code VARCHAR(128) NOT NULL UNIQUE,
    task_title VARCHAR(256) NOT NULL,
    task_type VARCHAR(64) NOT NULL,
    owner_agent VARCHAR(128) NOT NULL,
    priority VARCHAR(32) DEFAULT 'medium',
    risk_level VARCHAR(32) DEFAULT 'L2',
    status VARCHAR(32) DEFAULT 'created',
    scope TEXT,
    input_refs JSONB,
    output_refs JSONB,
    files_allowed JSONB,
    files_forbidden JSONB,
    acceptance_criteria JSONB,
    human_review_required BOOLEAN DEFAULT false,
    created_by VARCHAR(128),
    assigned_at TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_task_artifacts (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES agent_tasks(id),
    artifact_type VARCHAR(64) NOT NULL,
    artifact_path TEXT,
    artifact_summary TEXT,
    artifact_hash VARCHAR(128),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT REFERENCES agent_tasks(id),
    agent_name VARCHAR(128) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    command_text TEXT,
    files_changed JSONB,
    tables_touched JSONB,
    environment VARCHAR(32),
    risk_level VARCHAR(32),
    result_status VARCHAR(32),
    result_summary TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_human_review_gates (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES agent_tasks(id),
    gate_type VARCHAR(64) NOT NULL,
    reason TEXT,
    reviewer VARCHAR(128),
    review_status VARCHAR(32) DEFAULT 'pending',
    review_comment TEXT,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_code VARCHAR(128) NOT NULL,
    job_name VARCHAR(128) NOT NULL,
    owner_agent VARCHAR(128) NOT NULL,
    schedule_type VARCHAR(64),
    environment VARCHAR(32) DEFAULT 'prod',
    input_snapshot_refs JSONB,
    output_refs JSONB,
    status VARCHAR(32) NOT NULL,
    retry_count INT DEFAULT 0,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS codex_review_reports (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT REFERENCES agent_tasks(id),
    report_type VARCHAR(64) NOT NULL,
    test_command TEXT,
    pass_count INT,
    fail_count INT,
    coverage NUMERIC(10,4),
    report_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_owner ON agent_tasks(owner_agent);
CREATE INDEX IF NOT EXISTS idx_ai_job_runs_code_time ON ai_job_runs(job_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_logs_task ON agent_audit_logs(task_id);
